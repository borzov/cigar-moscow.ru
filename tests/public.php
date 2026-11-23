<?php

/**
 * @file
 * Exercises public lists with temporary revisions inside a rolled-back transaction.
 */

use Drupal\club_public\Controller\Catalogue;
use Drupal\node\Entity\Node;

$assert = static function (bool $condition, string $message): void {
  if (!$condition) {
    throw new RuntimeException($message);
  }
};
$transaction = \Drupal::database()->startTransaction();
try {
  $create = static function (string $bundle, string $title, array $values = []) {
    $node = Node::create($values + [
      'type' => $bundle, 'langcode' => 'ru', 'title' => $title, 'uid' => 1,
      'moderation_state' => 'published',
    ]);
    $node->save();
    return $node;
  };
  $cigar = $create('cigar', 'Public test cigar');
  foreach ([
    ['2020-01-01', 'Older collective', 91, 'published'],
    ['2021-01-01', 'Latest collective', 100, 'published'],
    ['2022-01-01', 'Newer draft', 62, 'draft'],
    ['2023-01-01', 'Individual result', NULL, 'published'],
  ] as [$date, $title, $score, $state]) {
    $create('tasting', $title, [
      'field_date' => $date, 'field_cigar' => $cigar->id(), 'field_club_score' => $score,
      'field_individual_score' => 58, 'moderation_state' => $state,
    ]);
  }
  $catalogue = static fn() => Catalogue::create(\Drupal::getContainer());
  $ranked = array_filter($catalogue()->rating()['list']['#rows'], static fn(array $row) => $row['id'] === (int) $cigar->id());
  $assert(count($ranked) === 1, 'Each cigar must have one entry.');
  $row = reset($ranked);
  $assert($row['score'] === 100 && (string) $row['source']['#title'] === 'Latest collective', 'Ranking must retain the latest published collective score.');
  $related = $catalogue()->related($cigar);
  $titles = array_map(static fn(array $row) => (string) $row['link']['#title'], $related['tasting']['#rows']);
  $assert(count($titles) === 3 && !in_array('Newer draft', $titles, TRUE), 'Related materials must exclude drafts.');

  $today = new DateTimeImmutable('today', new DateTimeZone('Europe/Moscow'));
  $festival = $create('festival', 'Public test season', [
    'field_date' => $today->format('Y-m-d'), 'field_end' => $today->modify('+1 day')->format('Y-m-d'),
    'field_promote' => $today->format('Y-m-d'), 'field_reg_start' => $today->format('Y-m-d'),
    'field_reg_end' => $today->format('Y-m-d'),
  ]);
  $home = $catalogue()->home();
  $assert(!isset($home['hero']) && (string) $home['season']['#link']['#title'] === $festival->label(), 'A promoted festival must replace the archive cover.');
  $assert($home['season']['#days'] === 0 && $home['season']['#registration'] && isset($home['festivals']), 'Opening-day countdown, registration and world festivals must be present.');
  $assert($home['#cache']['max-age'] === 0, 'Timed content must not remain in render cache.');
  $festival->set('field_reg_end', $today->modify('-1 day')->format('Y-m-d'));
  $assert(empty($catalogue()->related($festival)['registration']), 'Closed registration must lose its link.');
  $editorialErrors = static function ($node): array {
    $paths = [];
    foreach ($node->validate() as $violation) {
      if ($violation->getConstraint() instanceof \Drupal\club_public\Plugin\Validation\Constraint\ClubEditorialConstraint) {
        $paths[] = $violation->getPropertyPath();
      }
    }
    return $paths;
  };
  $event = $create('event', 'Public test event', ['field_date' => '2020-01-01', 'field_event_type' => 'club']);
  $album = Node::create(['type' => 'album', 'title' => 'Public test album']);
  $assert($editorialErrors($album) === ['field_event'], 'An album must reference an event or festival.');
  $album->set('field_event', $event->id());
  $assert(!$editorialErrors($album), 'An event is sufficient for an album.');
  $album->set('field_festival', $festival->id());
  $assert(!$editorialErrors($album), 'An album may reference both.');
  $album->set('field_event', NULL);
  $assert(!$editorialErrors($album), 'A festival is sufficient for an album.');

  $event->set('field_end', '2019-12-31');
  $assert($editorialErrors($event) === ['field_end'], 'Event end must not precede start.');
  $event->set('field_end', '2020-01-01');
  $assert(!$editorialErrors($event), 'Single-day event is valid.');
  $festival->set('field_end', $today->modify('-1 day')->format('Y-m-d'));
  $assert($editorialErrors($festival) === ['field_end', 'field_reg_end'], 'Both inverted festival ranges must be flagged.');
  $festival->set('field_end', NULL)->set('field_reg_start', NULL);
  $assert($editorialErrors($festival) === ['field_reg_start'], 'Registration end requires start.');
  $festival->set('field_reg_end', NULL);
  $assert(!$editorialErrors($festival), 'Registration may be omitted.');
  $festival->set('field_reg_start', $today->format('Y-m-d'));
  $assert($editorialErrors($festival) === ['field_reg_end'], 'Registration start requires end.');
  $festival->set('field_reg_end', $today->format('Y-m-d'));
  $assert(!$editorialErrors($festival), 'Same-day registration is valid.');
  print "Published collective rankings, draft exclusion, festival promotion, registration, album relationships and date validation passed.\n";
}
finally {
  $transaction->rollBack();
}
