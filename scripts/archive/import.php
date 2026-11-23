<?php

/** Import the reviewed pilot from an offline snapshot into the local site. */
use Drupal\Component\Utility\Html;
use Drupal\node\Entity\Node;
use Drupal\taxonomy\Entity\Term;
use Drupal\user\Entity\User;
use Drupal\club_legacy\LegacySource;

require_once __DIR__ . '/ArchiveFiles.php';

function archiveJson(string $path): array {
  if (!is_readable($path)) {
    throw new RuntimeException("Missing snapshot or manifest: $path");
  }
  return json_decode(file_get_contents($path), TRUE, flags: JSON_THROW_ON_ERROR);
}

function archiveTime(string $date): int {
  $day = DateTimeImmutable::createFromFormat('!Y-m-d', $date, new DateTimeZone('Europe/Moscow'));
  if (!$day || $day->format('Y-m-d') !== $date) {
    throw new RuntimeException("Invalid calendar date: $date");
  }
  return $day->getTimestamp();
}

/** Resolve stable IDs from the reviewed manifest at the point of import. */
function archiveField(mixed $value, string $name, array $nodes): mixed {
  if (!is_array($value)) {
    return $value;
  }
  if (array_is_list($value)) {
    return array_map(fn ($item) => archiveField($item, $name, $nodes), $value);
  }
  if (isset($value['ref'])) {
    return ['target_id' => ($nodes[$value['ref']] ?? throw new RuntimeException('Unresolved reference: ' . $value['ref']))->id()];
  }
  $vocabulary = match ($name) {
    'field_brand_term' => 'club_brands', 'field_country_term' => 'club_countries', 'field_rubrics' => 'club_rubrics',
    default => throw new RuntimeException("Unrecognized reference field: $name"),
  };
  $filter = isset($value['slug']) ? ['field_slug' => $value['slug']] : ['name' => $value['term']];
  $matches = \Drupal::entityTypeManager()->getStorage('taxonomy_term')->loadByProperties(['vid' => $vocabulary] + $filter);
  if (count($matches) > 1) {
    throw new RuntimeException('Ambiguous term: ' . json_encode($filter, JSON_UNESCAPED_UNICODE));
  }
  $term = reset($matches);
  if (!$term) {
    if (!isset($value['term'])) {
      throw new RuntimeException('Unknown journal rubric: ' . $value['slug']);
    }
    $term = Term::create(['vid' => $vocabulary, 'langcode' => 'ru', 'name' => $value['term']]);
    $term->save();
  }
  return ['target_id' => $term->id()];
}

function archiveBody(string $html, string $title, ArchiveFiles $files, array $targets, array &$attachments): string {
  $dom = Html::load($html);
  $urls = \Drupal::service('file_url_generator');
  foreach (iterator_to_array($dom->getElementsByTagName('img')) as $index => $image) {
    if ($files->isMissing($image->getAttribute('src'))) {
      $image->replaceWith($dom->createTextNode(' [Фотография отсутствует в архиве] '));
      continue;
    }
    $photo = $files->image($image->getAttribute('src'), $title, $index + 1);
    $item = $photo->field_media_image->first();
    $file = $item->entity;
    $image->setAttribute('src', $urls->generateString($file->getFileUri()));
    $image->setAttribute('data-entity-type', 'file');
    $image->setAttribute('data-entity-uuid', $file->uuid());
    if (!$image->getAttribute('alt')) {
      $image->setAttribute('alt', $item->alt);
    }
    $image->setAttribute('width', (string) $item->width);
    $image->setAttribute('height', (string) $item->height);
  }
  foreach (iterator_to_array($dom->getElementsByTagName('a')) as $link) {
    $href = $link->getAttribute('href');
    if ($files->isMissing($href)) {
      $link->replaceWith($dom->createTextNode($link->textContent . ' [Файл отсутствует в архиве]'));
      continue;
    }
    if ($files->isAttachment($href)) {
      $file = $files->document($href);
      $attachments[$file->id()] = ['target_id' => $file->id(), 'display' => 1, 'description' => trim($link->textContent)];
      $link->setAttribute('href', $urls->generateString($file->getFileUri()));
      continue;
    }
    $key = LegacySource::key($href);
    if ($key !== NULL && isset($targets[$key])) {
      $link->setAttribute('href', $targets[$key]);
    }
  }
  return Html::serialize($dom);
}

if (getenv('CLUB_LOCAL') !== '1') {
  throw new RuntimeException('Run the pilot in the local Docker environment.');
}
$directory = realpath(getenv('CLUB_ARCHIVE_DIR') ?: dirname(\Drupal::root()) . '/private/archive-pilot');
if (!$directory || !\Drupal::moduleHandler()->moduleExists('club_legacy')) {
  throw new RuntimeException('The offline snapshot and club_legacy must be available.');
}
$records = archiveJson(__DIR__ . '/pilot.json');
$inventory = archiveJson(__DIR__ . '/pilot-inventory.json');
$articles = [];
$publicImages = [];
$targets = [];
foreach ($records as $row) {
  $public = $row['published'] ?? TRUE;
  foreach ($row['redirects'] ?? [] as $source) {
    $key = LegacySource::key($source);
    if (!$public || $key === NULL || (isset($targets[$key]) && $targets[$key] !== $row['alias'])) {
      throw new RuntimeException("Invalid or conflicting redirect: $source");
    }
    $targets[$key] = $row['alias'];
  }
  foreach (array_unique(array_filter([$row['article'] ?? NULL, $row['cover_from'] ?? NULL, ...($row['images_from'] ?? [])])) as $id) {
    if (!isset($articles[$id])) {
      $path = "$directory/articles/$id.json";
      if (!isset($inventory['articles'][$id]) || hash_file('sha256', $path) !== $inventory['articles'][$id]) {
        throw new RuntimeException("Source article $id differs from the reviewed snapshot.");
      }
      $articles[$id] = archiveJson($path);
    }
    if ($public) {
      $article = $articles[$id];
      if ($id == ($row['article'] ?? NULL) || in_array($id, $row['images_from'] ?? [])) {
        $publicImages += array_fill_keys($article['images'], TRUE);
      }
      if ($id == ($row['cover_from'] ?? $row['article'] ?? NULL)) {
        $cover = $row['cover_url'] ?? ($article['preview'] ?: ($article['images'][0] ?? NULL));
        if ($cover) {
          $publicImages[$cover] = TRUE;
        }
      }
    }
  }
}
$missing = archiveJson("$directory/extraction-report.json")['failed_media'];
$knownMissing = array_merge(...array_values($inventory['missing']));
foreach ($missing as $url => $reason) {
  if (!in_array($url, $knownMissing, TRUE) || !preg_match('/\b(404|410)\b/', $reason)) {
    throw new RuntimeException("Unresolved download error: $url ($reason)");
  }
}
$files = new ArchiveFiles($directory, archiveJson("$directory/assets.json"), archiveJson("$directory/attachments.json"), $publicImages, $missing, array_column($articles, 'url'));
$storage = \Drupal::entityTypeManager()->getStorage('node');
$aliases = \Drupal::service('path_alias.manager');
$redirects = \Drupal::keyValue(LegacySource::COLLECTION);
$lock = \Drupal::lock();
if (!$lock->acquire('club_archive.import', 3600)) {
  throw new RuntimeException('A club archive import is already running.');
}
$account = \Drupal::service('account_switcher');
$account->switchTo(User::load(1));
$transaction = \Drupal::database()->startTransaction();
$nodes = [];
$created = 0;
try {
  foreach ($records as $row) {
    $id = $row['id'];
    $matches = $storage->loadByProperties(['field_source_id' => $id]);
    $node = reset($matches);
    if (isset($nodes[$id]) || count($matches) > 1 || ($node && $node->bundle() !== $row['type'])) {
      throw new RuntimeException("Conflicting archive ID: $id");
    }
    if (!$node) {
      if ($aliases->getPathByAlias($row['alias'], 'ru') !== $row['alias']) {
        throw new RuntimeException('Alias already assigned: ' . $row['alias']);
      }
      $article = $articles[$row['article'] ?? ''] ?? [];
      $title = $row['title'] ?? $article['title'];
      $documents = [];
      $html = archiveBody($row['body'] ?? $article['body'] ?? '', $title, $files, $targets, $documents);
      $node = Node::create([
        'type' => $row['type'], 'langcode' => 'ru', 'uid' => 1, 'title' => $title,
        'body' => ['value' => $html, 'format' => 'basic_html'],
        'field_source_id' => $id, 'field_legacy_url' => ['uri' => 'https://www.cigar-moscow.ru' . $row['source']],
        'moderation_state' => ($row['published'] ?? TRUE) ? 'published' : 'draft',
        'path' => ['alias' => $row['alias'], 'pathauto' => 0], 'promote' => FALSE,
      ]);
      if ($date = $row['created'] ?? $article['date'] ?? NULL) {
        $node->setCreatedTime(archiveTime($date));
      }
      foreach ($row['fields'] ?? [] as $name => $value) {
        $node->set($name, archiveField($value, $name, $nodes));
      }
      if ($documents) {
        $node->set('field_archive_documents', array_values($documents));
      }
      if ($coverId = $row['cover_from'] ?? $row['article'] ?? NULL) {
        $cover = $articles[$coverId];
        $url = $row['cover_url'] ?? ($cover['preview'] ?: ($cover['images'][0] ?? NULL));
        if ($url && !$files->isMissing($url)) {
          $node->set('field_cover', $files->image($url, $cover['title'], 1)->id());
        }
      }
      foreach ($row['images_from'] ?? [] as $articleId) {
        $gallery = $articles[$articleId];
        foreach ($gallery['images'] as $i => $url) {
          if ($files->isMissing($url)) {
            continue;
          }
          $node->field_images->appendItem($files->image($url, $gallery['title'], $i + 1)->id());
        }
      }
      $errors = $node->validate();
      if (count($errors)) {
        $messages = [];
        foreach ($errors as $error) {
          $messages[] = $error->getPropertyPath() . ': ' . $error->getMessage();
        }
        throw new RuntimeException("Validation failed for $id: " . implode(', ', $messages));
      }
      $node->save();
      $created++;
    }
    $nodes[$id] = $node;
    foreach ($row['redirects'] ?? [] as $source) {
      $key = LegacySource::key($source);
      $previous = $redirects->get($key);
      if ($previous && $previous !== $node->uuid()) {
        throw new RuntimeException("Conflicting existing redirect: $source");
      }
      if ($node->isPublished() && !$previous) {
        $redirects->set($key, $node->uuid());
      }
    }
  }
  // Preserve an original thumbnail even when the editor chose another cover.
  foreach ($articles as $article) {
    if ($article['preview'] && !$files->isMissing($article['preview'])) {
      $files->image($article['preview'], $article['title'], 1);
    }
  }
  unset($transaction);
}
catch (Throwable $error) {
  $transaction->rollBack();
  $files->rollbackFiles();
  throw $error;
}
finally {
  $account->switchBack();
  $lock->release('club_archive.import');
}
\Drupal\Core\Cache\Cache::invalidateTags(['4xx-response']);
printf("Archive pilot: %d created, %d existing.\n", $created, count($records) - $created);
