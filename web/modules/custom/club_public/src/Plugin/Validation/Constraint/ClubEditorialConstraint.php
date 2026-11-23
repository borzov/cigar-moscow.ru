<?php

namespace Drupal\club_public\Plugin\Validation\Constraint;

use Drupal\Core\StringTranslation\TranslatableMarkup;
use Drupal\Core\Validation\Attribute\Constraint;
use Symfony\Component\Validator\Constraint as SymfonyConstraint;

/**
 * Cross-field requirements for album relationships and calendar dates.
 */
#[Constraint(id: 'ClubEditorial', label: new TranslatableMarkup('Club editorial fields'), type: 'entity')]
final class ClubEditorialConstraint extends SymfonyConstraint {

  public string $album = 'Укажите событие или выпуск фестиваля для фотоальбома.';
  public string $endDate = 'Дата окончания не может быть раньше даты начала.';
  public string $registrationStart = 'Укажите дату открытия регистрации.';
  public string $registrationEnd = 'Укажите дату окончания регистрации.';
  public string $registrationOrder = 'Регистрация не может закончиться раньше даты открытия.';

}
