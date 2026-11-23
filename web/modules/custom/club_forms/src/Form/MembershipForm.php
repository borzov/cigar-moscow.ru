<?php

namespace Drupal\club_forms\Form;

/**
 * Application to join the club; may be embedded using the form builder.
 */
final class MembershipForm extends ApplicationForm {

  /**
   * {@inheritdoc}
   */
  public function getFormId(): string {
    return 'club_forms_membership';
  }

  /**
   * {@inheritdoc}
   */
  protected function buttonLabel(): string {
    return (string) $this->t('Отправить заявку');
  }

}
