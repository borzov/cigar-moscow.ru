<?php

/** Verify installed editorial access, login protection, encryption and timezone. */
use Drupal\encrypt\Entity\EncryptionProfile;
use Drupal\user\Entity\Role;

$assert = static function (bool $condition, string $description): void {
  if (!$condition) {
    throw new RuntimeException($description);
  }
};
$assert(\Drupal::config('user.settings')->get('register') === 'admin_only', 'Only staff can create accounts.');
$assert(\Drupal::config('system.date')->get('timezone.default') === 'Europe/Moscow', 'Moscow calendar.');
$tfa = \Drupal::config('tfa.settings');
$assert((bool) $tfa->get('enabled') && in_array('authenticated', $tfa->get('required_roles'), TRUE), 'Staff TOTP required.');
$assert($tfa->get('default_validation_plugin') === 'tfa_totp', 'Authenticator app selected.');
$assert(Role::load('authenticated')->hasPermission('setup own tfa'), 'Enrollment available.');
$profile = EncryptionProfile::load($tfa->get('encryption'));
$service = \Drupal::service('encryption');
$test = bin2hex(random_bytes(16));
$assert($service->decrypt($service->encrypt($test, $profile), $profile) === $test, 'TOTP key works.');
$perm = 'view private club applications';
foreach (['anonymous', 'authenticated', 'club_author', 'club_editor'] as $role) {
  $assert(!Role::load($role)->hasPermission($perm), 'Private applications inaccessible to ' . $role);
}
$assert(Role::load('club_organizer')->hasPermission($perm), 'Organizers can open applications.');
echo "Editorial configuration verified.\n";
