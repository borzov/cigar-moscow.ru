<?php

namespace Drupal\club_forms\Form;

use Drupal\Core\Database\DatabaseException;
use Drupal\Core\Form\FormBase;
use Drupal\Core\Form\FormStateInterface;
use Drupal\Core\Site\Settings;
use Drupal\Core\Url;

/**
 * Shared contact fields, explicit consent and private storage.
 */
abstract class ApplicationForm extends FormBase {

  public const CONSENT_VERSION = '1';
  protected const FLOOD_EVENT = 'club_forms.application';

  /**
   * Returns the action label for this form.
   */
  abstract protected function buttonLabel(): string;

  /**
   * {@inheritdoc}
   */
  public function buildForm(array $form, FormStateInterface $form_state): array {
    // Give every rendered form its own Drupal form_build_id, including embeds.
    \Drupal::service('page_cache_kill_switch')->trigger();
    $form['#cache']['max-age'] = 0;
    $form['applicant_name'] = [
      '#type' => 'textfield',
      '#title' => $this->t('Имя'),
      '#required' => TRUE,
      '#maxlength' => 120,
      '#attributes' => ['autocomplete' => 'name'],
    ];
    $form['email'] = [
      '#type' => 'email',
      '#title' => $this->t('Электронная почта'),
      '#required' => TRUE,
      '#maxlength' => 254,
      '#attributes' => ['autocomplete' => 'email'],
    ];
    $form['consent'] = [
      '#type' => 'checkbox',
      '#title' => $this->t('Я даю согласие на обработку имени и электронной почты для рассмотрения моей заявки.'),
      '#description' => $this->t('<a href=":privacy">Условия обработки персональных данных</a>', [':privacy' => Url::fromUserInput('/privacy')->toString()]),
      '#required' => TRUE,
    ];
    $form['actions']['#type'] = 'actions';
    $form['actions']['submit'] = ['#type' => 'submit', '#value' => $this->buttonLabel()];
    return $form;
  }

  /**
   * {@inheritdoc}
   */
  public function validateForm(array &$form, FormStateInterface $form_state): void {
    $build_id = $form_state->getUserInput()['form_build_id'] ?? NULL;
    if (!is_string($build_id) || !preg_match('/^form-[A-Za-z0-9_-]{43}$/D', $build_id)) {
      $form_state->setErrorByName('', $this->t('Обновите страницу и отправьте заявку ещё раз.'));
      return;
    }
    $key = hash('sha256', $this->getFormId() . ':' . $form_state->get('festival_nid') . ':' . $build_id);
    $form_state->set('submission_key', $key);
    if (\Drupal::database()->select('club_application', 'a')->fields('a', ['id'])
      ->condition('submission_key', $key)->execute()->fetchField()) {
      return;
    }
    $flood = \Drupal::flood();
    $identifier = hash_hmac('sha256', (string) $this->getRequest()->getClientIp(), Settings::getHashSalt());
    if (!$flood->isAllowed(self::FLOOD_EVENT, 5, 3600, $identifier)) {
      $form_state->setErrorByName('', $this->t('Слишком много попыток. Попробуйте через час.'));
      return;
    }
    $flood->register(self::FLOOD_EVENT, 3600, $identifier);
    if (!preg_match('/\S/u', (string) $form_state->getValue('applicant_name'))) {
      $form_state->setErrorByName('applicant_name', $this->t('Введите ваше имя.'));
    }
  }

  /**
   * {@inheritdoc}
   */
  public function submitForm(array &$form, FormStateInterface $form_state): void {
    $festival = $form_state->get('festival_nid');
    try {
      // Merge handles concurrent inserts on the unique submission key.
      \Drupal::database()->merge('club_application')->insertFields([
        'kind' => $festival === NULL ? 'membership' : 'festival',
        'festival_nid' => $festival,
        'applicant_name' => trim($form_state->getValue('applicant_name')),
        'email' => trim($form_state->getValue('email')),
        'consent_version' => self::CONSENT_VERSION,
        'consented' => \Drupal::time()->getCurrentTime(),
      ])->key('submission_key', $form_state->get('submission_key'))->execute();
    }
    catch (DatabaseException) {
      // A database exception can contain the submitted field values.
      $this->getLogger('club_forms')->error('Failed to store a club application.');
      $this->messenger()->addError($this->t('Не удалось сохранить заявку. Попробуйте позже.'));
      $form_state->setRebuild();
      return;
    }
    $this->messenger()->addStatus($this->t('Ваша заявка принята.'));
  }

}
