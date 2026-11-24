<?php

use Drupal\Core\File\FileSystemInterface;
use Drupal\file\Entity\File;
use Drupal\media\Entity\Media;

/** Imports the files in the offline snapshot and reuses their Drupal entities. */
final class ArchiveFiles {
  private array $media = [];
  private array $existingPhotos = [];
  private array $written = [];
  private array $documents = [];

  public function __construct(
    private readonly string $directory,
    private readonly array $assets,
    private readonly array $attachments,
    private readonly array $publicImages,
    private readonly array $missing,
    array $articleUrls,
  ) {
    // The initial site already uses two photographs credited to the original report.
    $storage = \Drupal::entityTypeManager()->getStorage('media');
    $ids = $storage->getQuery()->accessCheck(FALSE)->condition('bundle', 'image')
      ->condition('status', 1)->condition('field_legacy_url.uri', $articleUrls, 'IN')->execute();
    foreach ($storage->loadMultiple($ids) as $photo) {
      $uri = $photo->field_media_image->entity?->getFileUri();
      if ($uri && is_file($uri)) {
        $this->existingPhotos[hash_file('sha256', $uri)] = $photo;
      }
    }
  }

  public function image(string $url, string $articleTitle, int $position): Media {
    if (isset($this->media[$url])) {
      return $this->media[$url];
    }
    $asset = $this->assets[$url] ?? throw new RuntimeException("Missing image metadata: $url");
    $isPublic = isset($this->publicImages[$url]);
    $map = \Drupal::keyValue('club_archive.media');
    $uuid = $map->get(hash('sha256', $url));
    $photo = $uuid ? \Drupal::service('entity.repository')->loadEntityByUuid('media', $uuid) : NULL;
    if (!$photo && $isPublic) {
      $photo = $this->existingPhotos[$asset['sha256']] ?? NULL;
    }
    if (!$photo) {
      [$file, $size] = $this->file($asset, $isPublic, FALSE);
      $name = trim($asset['alt'] ?? '') ?: "$articleTitle — фото $position";
      $photo = Media::create([
        'bundle' => 'image', 'langcode' => 'ru', 'status' => $isPublic,
        'name' => mb_substr($name, 0, 255), 'uid' => 1,
        'field_media_image' => ['target_id' => $file->id(), 'alt' => mb_substr($name, 0, 512), 'width' => $size[0], 'height' => $size[1]],
        'field_credit' => 'Фотоархив Московских Афисионадо', 'field_legacy_url' => ['uri' => $url],
      ]);
      $photo->save();
    }
    $map->set(hash('sha256', $url), $photo->uuid());
    return $this->media[$url] = $photo;
  }

  public function isMissing(string $url): bool {
    return isset($this->missing[$url]);
  }

  public function isAttachment(string $url): bool {
    return isset($this->attachments[$url]);
  }

  public function document(string $url): File {
    if (!isset($this->documents[$url])) {
      [$this->documents[$url]] = $this->file($this->attachments[$url], FALSE, TRUE);
    }
    return $this->documents[$url];
  }

  private function file(array $asset, bool $public, bool $pdf): array {
    $input = realpath($this->directory . '/' . $asset['file']);
    if (!$input || !str_starts_with($input, $this->directory . '/') || !is_file($input) ||
      hash_file('sha256', $input) !== $asset['sha256']) {
      throw new RuntimeException('Snapshot integrity error: ' . $asset['file']);
    }
    $size = $pdf ? [] : getimagesize($input);
    $type = $pdf ? 'application/pdf' : ($size['mime'] ?? '');
    $extension = match ($type) {
      'image/jpeg' => 'jpg', 'image/png' => 'png', 'image/gif' => 'gif',
      'image/webp' => 'webp', 'application/pdf' => 'pdf',
      default => throw new RuntimeException('Unsupported file type: ' . $asset['file']),
    };
    if ($pdf && file_get_contents($input, FALSE, NULL, 0, 5) !== '%PDF-') {
      throw new RuntimeException('Invalid PDF: ' . $asset['file']);
    }
    $hash = $asset['sha256'];
    $directory = ($public ? 'public://' : 'private://') . 'legacy/' . substr($hash, 0, 2);
    $uri = "$directory/$hash.$extension";
    $fs = \Drupal::service('file_system');
    if (!$fs->prepareDirectory($directory, FileSystemInterface::CREATE_DIRECTORY)) {
      throw new RuntimeException("Cannot create $directory");
    }
    if (is_file($uri)) {
      if (hash_file('sha256', $uri) !== $hash) {
        throw new RuntimeException("Existing file differs: $uri");
      }
    }
    else {
      $this->written[] = $uri;
      if (!copy($input, $uri)) {
        throw new RuntimeException("Cannot write $uri");
      }
      $fs->chmod($uri);
    }
    $matches = \Drupal::entityTypeManager()->getStorage('file')->loadByProperties(['uri' => $uri]);
    $file = reset($matches);
    if (!$file) {
      $file = File::create(['uri' => $uri, 'filename' => "$hash.$extension", 'filemime' => $type, 'uid' => 1, 'status' => 1]);
      $file->save();
    }
    return [$file, $size];
  }

  public function writtenCount(): int {
    return count($this->written);
  }

  public function rollbackFrom(int $index): void {
    foreach (array_slice($this->written, $index) as $uri) {
      if (is_file($uri)) {
        \Drupal::service('file_system')->delete($uri);
      }
    }
    $this->written = array_slice($this->written, 0, $index);
  }

  public function rollbackFiles(): void {
    $this->rollbackFrom(0);
  }
}
