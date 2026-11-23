<?php

namespace Drupal\club_legacy;

/**
 * Converts an archive URL into the exact lookup key shared with the importer.
 */
final class LegacySource {

  public const COLLECTION = 'club_legacy.redirects';

  /**
   * Normalizes legacy paths and query order, preserving semantic parameters.
   */
  public static function key(string $source): ?string {
    $parts = parse_url($source);
    if (!$parts || str_starts_with($source, '//') || isset($parts['port']) || isset($parts['user'])) {
      return NULL;
    }
    if (isset($parts['scheme']) || isset($parts['host'])) {
      if (!in_array(strtolower($parts['scheme'] ?? ''), ['http', 'https'], TRUE)
        || !in_array(strtolower($parts['host'] ?? ''), ['cigar-moscow.ru', 'www.cigar-moscow.ru'], TRUE)) {
        return NULL;
      }
    }
    $path = strtolower($parts['path'] ?? '');
    if (!preg_match('~^/[a-z0-9_/-]+\.html$~D', $path)) {
      return NULL;
    }
    $query = [];
    foreach (explode('&', $parts['query'] ?? '') as $pair) {
      if ($pair === '') {
        continue;
      }
      [$name, $value] = array_pad(explode('=', $pair, 2), 2, '');
      $name = strtolower(urldecode($name));
      if (str_starts_with($name, 'utm_') || in_array($name, ['gclid', 'fbclid', 'yclid'], TRUE)) {
        continue;
      }
      if ($name === '' || array_key_exists($name, $query)) {
        return NULL;
      }
      $query[$name] = urldecode($value);
    }
    ksort($query, SORT_STRING);
    $key = $path . ($query ? '?' . http_build_query($query, '', '&', PHP_QUERY_RFC3986) : '');
    // Drupal's database-backed key/value store accepts keys up to 128 bytes.
    return strlen($key) <= 128 ? $key : NULL;
  }

}
