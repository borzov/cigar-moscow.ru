<?php

namespace Drupal\club_forms;

use Drupal\Core\Access\AccessResult;
use Drupal\Core\Access\AccessResultInterface;
use Drupal\node\NodeInterface;

/**
 * Registration runs through the end of the final calendar day in Moscow.
 */
final class RegistrationWindow {

  /**
   * Checks publication and the inclusive registration period.
   */
  public static function isOpen(NodeInterface $node): bool {
    if ($node->bundle() !== 'festival' || !$node->isPublished() || !$node->hasField('field_reg_start') || !$node->hasField('field_reg_end')) {
      return FALSE;
    }
    $today = (new \DateTimeImmutable('@' . \Drupal::time()->getCurrentTime()))
      ->setTimezone(new \DateTimeZone('Europe/Moscow'))->format('Y-m-d');
    $start = $node->get('field_reg_start')->value;
    $end = $node->get('field_reg_end')->value;
    return $start && $end && $start <= $today && $today <= $end;
  }

  /**
   * Checks registration access for the public route.
   */
  public function access(NodeInterface $node): AccessResultInterface {
    return AccessResult::allowedIf(self::isOpen($node))->addCacheableDependency($node)->setCacheMaxAge(0);
  }

}
