<?php

namespace Drupal\club_forms\Controller;

use Drupal\Core\Controller\ControllerBase;
use Drupal\Core\Database\Query\PagerSelectExtender;

/**
 * Restricted read-only list of private applications.
 */
final class ApplicationsController extends ControllerBase {

  /**
   * Builds a paginated list for staff with access to private submissions.
   */
  public function listing(): array {
    $rows = [];
    $query = \Drupal::database()->select('club_application', 'a')->extend(PagerSelectExtender::class);
    $result = $query->fields('a')->orderBy('id', 'DESC')->limit(50)->execute();
    $dates = \Drupal::service('date.formatter');
    foreach ($result as $record) {
      $rows[] = [
        $record->kind === 'membership' ? $this->t('Вступление') : $this->t('Фестиваль № @id', ['@id' => $record->festival_nid]),
        ['data' => ['#plain_text' => $record->applicant_name]],
        ['data' => ['#plain_text' => $record->email]],
        $dates->format($record->consented, 'custom', 'd.m.Y H:i', 'Europe/Moscow'),
        ['data' => ['#plain_text' => $record->consent_version]],
      ];
    }
    return [
      '#cache' => ['max-age' => 0],
      'list' => [
        '#type' => 'table',
        '#header' => [
          $this->t('Заявка'),
          $this->t('Имя'),
          $this->t('Электронная почта'),
          $this->t('Согласие (МСК)'),
          $this->t('Версия согласия'),
        ],
        '#rows' => $rows,
        '#empty' => $this->t('Заявок пока нет.'),
      ],
      'pager' => ['#type' => 'pager'],
    ];
  }

}
