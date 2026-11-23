<?php

/** Verify the installed pilot against its editorial manifest and offline assets. */
use Drupal\club_legacy\LegacySource;
use Drupal\Component\Utility\Html;

function archiveCheck(bool $condition, string $message): void {
  if (!$condition) {
    throw new RuntimeException($message);
  }
}

function archiveRead(string $path): array {
  return json_decode(file_get_contents($path), TRUE, flags: JSON_THROW_ON_ERROR);
}

$root = dirname(\Drupal::root());
$dir = getenv('CLUB_ARCHIVE_DIR') ?: "$root/private/archive-pilot";
$manifest = archiveRead("$root/scripts/archive/pilot.json");
$storage = \Drupal::entityTypeManager()->getStorage('node');
$images = [];
$mediaMap = \Drupal::keyValue('club_archive.media');
$repository = \Drupal::service('entity.repository');
foreach (archiveRead("$dir/assets.json") as $url => $asset) {
  $uuid = $mediaMap->get(hash('sha256', $url));
  $photo = $uuid ? $repository->loadEntityByUuid('media', $uuid) : NULL;
  archiveCheck($photo !== NULL, "Missing original photograph: $url");
  $file = $photo->field_media_image->entity;
  archiveCheck($file && hash_file('sha256', $file->getFileUri()) === $asset['sha256'], "Original bytes differ: $url");
  $images[$url] = ['media' => $photo->id(), 'file' => $file->uuid()];
}
$redirects = \Drupal::keyValue(LegacySource::COLLECTION);
$articles = [];
$missing = archiveRead("$dir/extraction-report.json")['failed_media'];
$documents = archiveRead("$dir/attachments.json");
$verifiedDocuments = [];
foreach ($manifest as $row) {
  $id = $row['id'];
  $found = $storage->loadByProperties(['field_source_id' => $id]);
  archiveCheck(count($found) === 1, "Missing or duplicate: $id");
  $node = reset($found);
  archiveCheck($node->bundle() === $row['type'] && !$node->field_demo->value, "Wrong type or demo flag: $id");
  archiveCheck($node->isPublished() === ($row['published'] ?? TRUE), "Unexpected publication state: $id");
  $incoming = \Drupal::service('path_alias.manager')->getPathByAlias($row['alias'], 'ru');
  archiveCheck($incoming === '/node/' . $node->id(), 'Missing alias: ' . $row['alias']);
  if (isset($row['cover_url'])) {
    archiveCheck((string) $node->field_cover->target_id === (string) $images[$row['cover_url']]['media'], "Wrong selected cover: $id");
  }
  foreach ($row['redirects'] ?? [] as $source) {
    archiveCheck($redirects->get(LegacySource::key($source)) === $node->uuid(), "Missing mapping: $source");
  }
  foreach (['field_club_score', 'field_individual_score', 'field_score_original', 'field_date'] as $name) {
    if ($node->hasField($name)) {
      archiveCheck((string) $node->get($name)->value === (string) ($row['fields'][$name] ?? ''), "Wrong $name: $id");
    }
  }
  foreach ($row['fields'] ?? [] as $field => $value) {
    if (is_array($value) && isset($value['ref'])) {
      archiveCheck($node->get($field)->entity?->field_source_id->value === $value['ref'], "Broken $field: $id");
    }
  }
  if (isset($row['article'])) {
    $article = $articles[$row['article']] ??= archiveRead("$dir/articles/{$row['article']}.json");
    archiveCheck((new DateTimeImmutable('@' . $node->getCreatedTime()))->setTimezone(new DateTimeZone('Europe/Moscow'))->format('Y-m-d') === $article['date'], "Wrong publication date: $id");
    $expected = Html::load($article['body']);
    foreach (iterator_to_array($expected->getElementsByTagName('img')) as $img) {
      if (isset($missing[$img->getAttribute('src')])) {
        $img->replaceWith($expected->createTextNode(' [Фотография отсутствует в архиве] '));
      }
    }
    foreach (iterator_to_array($expected->getElementsByTagName('a')) as $a) {
      if (isset($missing[$a->getAttribute('href')])) {
        $a->replaceWith($expected->createTextNode($a->textContent . ' [Файл отсутствует в архиве]'));
      }
    }
    $stored = Html::load($node->body->value);
    $expectedDocuments = [];
    foreach ($expected->getElementsByTagName('a') as $link) {
      $url = $link->getAttribute('href');
      if (isset($documents[$url])) {
        $expectedDocuments[$url] = $documents[$url]['sha256'];
      }
    }
    $actualDocuments = [];
    foreach ($node->field_archive_documents->referencedEntities() as $file) {
      archiveCheck(str_starts_with($file->getFileUri(), 'private://'), "Public archive attachment: $id");
      $actualDocuments[] = hash_file('sha256', $file->getFileUri());
    }
    archiveCheck(array_values($expectedDocuments) === $actualDocuments, "Attachment bytes or order differ: $id");
    $verifiedDocuments += $expectedDocuments;
    $words = static fn ($doc) => preg_replace('/\s+/u', ' ', trim($doc->getElementsByTagName('body')->item(0)->textContent));
    archiveCheck($words($expected) === $words($stored), "Body text differs: $id");
    $expectedFiles = [];
    foreach ($expected->getElementsByTagName('img') as $img) {
      $expectedFiles[] = $images[$img->getAttribute('src')]['file'];
    }
    $storedFiles = [];
    foreach ($stored->getElementsByTagName('img') as $img) {
      archiveCheck(str_starts_with($img->getAttribute('src'), '/'), "External image: $id");
      $storedFiles[] = $img->getAttribute('data-entity-uuid');
    }
    archiveCheck($storedFiles === $expectedFiles, "Photograph order differs: $id");
  }
  if (isset($row['images_from'])) {
    $expectedIds = [];
    foreach ($row['images_from'] as $sourceId) {
      $article = $articles[$sourceId] ??= archiveRead("$dir/articles/$sourceId.json");
      foreach ($article['images'] as $url) {
        if (isset($images[$url])) {
          $expectedIds[] = (string) $images[$url]['media'];
        }
      }
    }
    $actualIds = array_map('strval', array_column($node->field_images->getValue(), 'target_id'));
    archiveCheck($actualIds === $expectedIds, "Album order or membership differs: $id");
  }
}
archiveCheck(count($verifiedDocuments) === count($documents), 'Unreferenced archive attachment');
printf("Verified %d unique records, %d source articles, %d original images and %d private attachments.\n", count($manifest), count($articles), count($images), count($verifiedDocuments));
