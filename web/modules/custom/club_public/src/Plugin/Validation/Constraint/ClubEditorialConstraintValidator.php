<?php

namespace Drupal\club_public\Plugin\Validation\Constraint;

use Symfony\Component\Validator\Constraint;
use Symfony\Component\Validator\ConstraintValidator;

/**
 * Ensures that related editorial fields form a usable publication.
 */
final class ClubEditorialConstraintValidator extends ConstraintValidator {

  public function validate(mixed $node, Constraint $constraint): void {
    if ($node->bundle() === 'album' && $node->get('field_event')->isEmpty() && $node->get('field_festival')->isEmpty()) {
      $this->context->buildViolation($constraint->album)->atPath('field_event')->addViolation();
    }
    if (!in_array($node->bundle(), ['event', 'festival'], TRUE)) {
      return;
    }

    // Drupal date-only fields store ISO dates, which sort chronologically.
    $start = $node->get('field_date')->value;
    $end = $node->get('field_end')->value;
    if ($start && $end && $end < $start) {
      $this->context->buildViolation($constraint->endDate)->atPath('field_end')->addViolation();
    }
    if ($node->bundle() === 'festival') {
      $open = $node->get('field_reg_start')->value;
      $close = $node->get('field_reg_end')->value;
      if ($close && !$open) {
        $this->context->buildViolation($constraint->registrationStart)->atPath('field_reg_start')->addViolation();
      }
      elseif ($open && !$close) {
        $this->context->buildViolation($constraint->registrationEnd)->atPath('field_reg_end')->addViolation();
      }
      elseif ($open && $close < $open) {
        $this->context->buildViolation($constraint->registrationOrder)->atPath('field_reg_end')->addViolation();
      }
    }
  }

}
