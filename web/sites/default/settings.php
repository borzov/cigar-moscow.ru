<?php

// Supply credentials in the host environment or in a file outside the web root.
$host_settings = dirname(__DIR__, 3) . '/settings.host.php';
if (is_file($host_settings)) {
  require $host_settings;
}
else {
  $databases['default']['default'] = [
    'driver' => 'mysql',
    'namespace' => 'Drupal\\mysql\\Driver\\Database\\mysql',
    'database' => getenv('MYSQL_DATABASE'),
    'username' => getenv('MYSQL_USER'),
    'password' => getenv('MYSQL_PASSWORD'),
    'host' => 'db',
    'port' => 3306,
    'prefix' => '',
    // MySQL generates its own certificate on this internal Docker network.
    'pdo' => [\Pdo\Mysql::ATTR_SSL_VERIFY_SERVER_CERT => FALSE],
  ];
  $settings['hash_salt'] = getenv('DRUPAL_HASH_SALT');
  $settings['trusted_host_patterns'] = ['^localhost$', '^127\\.0\\.0\\.1$'];
}
$settings['config_sync_directory'] = dirname(__DIR__, 3) . '/config/sync';
$settings['file_private_path'] ??= dirname(__DIR__, 3) . '/private/files';
$settings['update_free_access'] = FALSE;
