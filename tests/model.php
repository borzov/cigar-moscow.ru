<?php

/**
 * @file
 * Read-only smoke checks for a freshly installed club demonstration site.
 */

use Drupal\field\Entity\FieldConfig;
use Drupal\node\Entity\Node;
use Drupal\node\NodeInterface;
use Drupal\taxonomy\Entity\Vocabulary;
use Drupal\user\Entity\Role;
use Drupal\workflows\Entity\Workflow;

$check = static function (bool $condition, string $message): void {
  if (!$condition) {
    throw new RuntimeException($message);
  }
};
$by_alias = static function (string $alias, string $language = 'ru') use ($check): NodeInterface {
  $path = \Drupal::service('path_alias.manager')->getPathByAlias($alias, $language);
  $check((bool) preg_match('~^/node/([0-9]+)$~', $path, $matches), "Missing $language alias $alias");
  $node = Node::load($matches[1]);
  $check($node && $node->hasTranslation($language), "Missing $language translation for $alias");
  $translation = $node->getTranslation($language);
  $check($translation->isPublished(), "Unpublished translation at $alias ($language)");
  return $translation;
};
foreach (['/club', '/contacts'] as $path) {
  $ru = $by_alias($path);
  $en = $by_alias($path, 'en');
  $check($ru->id() === $en->id() && $ru->label() !== $en->label(), "Translation mismatch on $path");
}
$workflow = Workflow::load('editorial')->getTypePlugin();
foreach (['club_page', 'cigar', 'tasting', 'event', 'festival', 'journal', 'album'] as $bundle) {
  $check($workflow->appliesToEntityTypeAndBundle('node', $bundle), "Missing moderation for $bundle");
}
$author = Role::load('club_author');
$check($author->hasPermission('use editorial transition create_new_draft'), 'Author cannot draft');
$check(!$author->hasPermission('use editorial transition publish'), 'Author can publish');
$check(Role::load('club_editor')->hasPermission('use editorial transition publish'), 'Editor cannot publish');

$tasting = $by_alias('/tastings/demo-session');
$cigar = $by_alias('/cigars/demo-edition');
$event = $by_alias('/events/demo-club-evening');
$festival = $by_alias('/festivals/demo-edition');
$upcoming = $by_alias('/festivals/demo-upcoming');
$installed = (new DateTimeImmutable('@' . $upcoming->getCreatedTime()))
  ->setTimezone(new DateTimeZone('Europe/Moscow'))->format('Y-m-d');
$check($upcoming->field_reg_start->value <= $installed && $installed <= $upcoming->field_reg_end->value, 'Demo registration window at first installation');
$check($upcoming->field_promote->value <= $installed, 'Festival promotion visible on installation');
$check($installed < $upcoming->field_date->value && $upcoming->field_date->value <= $upcoming->field_end->value, 'Future festival dates');
$album = $by_alias('/albums/demo-evening');
$journal = $by_alias('/journal/demo-tea');
$term_storage = \Drupal::entityTypeManager()->getStorage('taxonomy_term');
$editor = Role::load('club_editor');
foreach (['club_brands', 'club_countries', 'club_rubrics'] as $vid) {
  $check((bool) Vocabulary::load($vid), "Missing vocabulary $vid");
  $check($editor->hasPermission("create terms in $vid") && $editor->hasPermission("edit terms in $vid"), "Editor cannot maintain $vid");
  $check(!$author->hasPermission("edit terms in $vid"), "Author can edit $vid terms");
}
$second_cigar = $by_alias('/cigars/demo-corona');
$check($cigar->field_brand_term->entity->bundle() === 'club_brands', 'Cigar brand vocabulary');
$check($cigar->field_brand_term->target_id === $second_cigar->field_brand_term->target_id, 'Shared cigar brand');
$check($cigar->field_country_term->entity->label() === 'Никарагуа' && $second_cigar->field_country_term->entity->label() === 'Доминиканская Республика', 'Cigar country terms');
$check($journal->field_rubrics->entity->field_slug->value === 'pairing_tea', 'Stable tea pairing rubric key');
$check($journal->getFieldDefinition('field_rubrics')->getFieldStorageDefinition()->isMultiple(), 'Journal must allow several rubrics');
foreach (['club', 'interview', 'digest', 'portrait', 'travel', 'vintage', 'humidor', 'guide', 'pairing_cigar', 'pairing_tea', 'pairing_drink'] as $slug) {
  $terms = $term_storage->loadByProperties(['vid' => 'club_rubrics', 'field_slug' => $slug]);
  $check(count($terms) === 1, "Missing or duplicate seeded rubric $slug");
}
$check($by_alias('/tastings/demo-personal')->field_cigar->target_id === $tasting->field_cigar->target_id && !$tasting->field_score_original->isEmpty(), 'Archival provenance and repeat observations');
$check($tasting->field_cigar->target_id === $cigar->id(), 'Tasting-to-cigar reference');
$check($tasting->field_event->target_id === $event->id(), 'Tasting-to-event reference');
$check($event->field_festival->target_id === $festival->id(), 'Event-to-festival reference');
$check($album->field_event->target_id === $event->id() && $album->field_festival->target_id === $festival->id(), 'Album relationships');
$check($album->field_images->count() === 2, 'The demo album must contain two media items');
foreach ($album->field_images->referencedEntities() as $media) {
  $check(!$media->field_media_image->isEmpty() && !$media->field_credit->isEmpty() && !$media->field_legacy_url->isEmpty(), 'Missing photograph or credit');
  $check(file_exists($media->field_media_image->entity->getFileUri()), 'Missing uploaded file');
}
$check($journal->field_cigars->count() === 2 && $journal->field_festival->target_id === $festival->id(), 'Journal relationships');
$check($by_alias('/tastings/demo-personal')->field_club_score->isEmpty(), 'An individual-only tasting must have no club score');
foreach (['field_club_score', 'field_individual_score'] as $name) {
  $definition = FieldConfig::loadByName('node', 'tasting', $name);
  $check($definition->getType() === 'integer', "$name must store integers");
  foreach ([0 => TRUE, 100 => TRUE, -1 => FALSE, 101 => FALSE] as $score => $valid) {
    $tasting->set($name, $score);
    $check(($tasting->get($name)->validate()->count() === 0) === $valid, "$name boundary at $score");
  }
}
print "Club model, translations, permissions, score constraints and demonstration links passed.\n";
