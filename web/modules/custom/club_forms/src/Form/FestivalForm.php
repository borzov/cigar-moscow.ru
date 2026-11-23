<?php

namespace Drupal\club_forms\Form;

use Drupal\club_forms\RegistrationWindow;
use Drupal\Core\Form\FormStateInterface;
use Drupal\node\NodeInterface;
use Symfony\Component\HttpKernel\Exception\AccessDeniedHttpException;

/**
 * Registration for a specific published festival.
 */
final class FestivalForm extends ApplicationForm {

  /**
   * {@inheritdoc}
   */
  public function getFormId(): string {
    return 'club_forms_festival';
  }

  /**
   * {@inheritdoc}
   */
  protected function buttonLabel(): string {
    return (string) $this->t('Зарегистрироваться');
  }

  /**
   * {@inheritdoc}
   */
  public function buildForm(array $form, FormStateInterface $form_state, ?NodeInterface $node = NULL): array {
    if (!$node || !RegistrationWindow::isOpen($node) || !$node->access('view')) {
      throw new AccessDeniedHttpException();
    }
    $form_state->set('festival_nid', $node->id());
    $form['festival'] = ['#plain_text' => $node->label()];
    return parent::buildForm($form, $form_state);
  }

  /**
   * {@inheritdoc}
   */
  public function submitForm(array &$form, FormStateInterface $form_state): void {
    $node = \Drupal::entityTypeManager()->getStorage('node')->loadUnchanged($form_state->get('festival_nid'));
    if (!$node || !RegistrationWindow::isOpen($node) || !$node->access('view')) {
      throw new AccessDeniedHttpException();
    }
    parent::submitForm($form, $form_state);
  }

}
