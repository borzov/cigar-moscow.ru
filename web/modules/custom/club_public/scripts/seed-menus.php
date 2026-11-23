<?php

use Drupal\language\Entity\ContentLanguageSettings;
use Drupal\menu_link_content\Entity\MenuLinkContent;

// Menu links are content. Seed once after importing configuration and aliases.
if (\Drupal::state()->get('club_public.menus_seeded')) {
  return;
}
$transaction = \Drupal::database()->startTransaction();
try {
  ContentLanguageSettings::loadByEntityTypeBundle('menu_link_content', 'menu_link_content')
    ->setThirdPartySetting('content_translation', 'enabled', TRUE)->save();
  $menus = [
    'club-header' => [
      ['/club', 'Клуб', 'Club'], ['/festival', 'Фестиваль', 'Festival'],
      ['/events', 'События', 'Events'], ['/cigars', 'Сигары', 'Cigars'],
      ['/journal', 'Журнал', 'Journal'], ['/contacts', 'Контакты', 'Contacts'],
    ],
    'club-footer' => [
      ['/gallery', 'Фотоальбомы', 'Photo albums'], ['/rating', 'Рейтинг сигар', 'Cigar rating'],
      ['/events/archive', 'Архив событий', 'Event archive'], ['/membership', 'Вступление в клуб', 'Membership'],
      ['/contacts', 'Контакты', 'Contacts'], ['/privacy', 'Обработка данных', 'Data processing'],
      ['/club/terms', 'Условия участия', 'Participation terms'],
    ],
  ];
  foreach ($menus as $menu => $entries) {
    foreach ($entries as $weight => [$path, $ru, $en]) {
      $link = MenuLinkContent::create([
        'menu_name' => $menu, 'langcode' => 'ru', 'title' => $ru,
        'link' => ['uri' => 'internal:' . $path], 'weight' => $weight,
      ]);
      $link->addTranslation('en', ['title' => $en, 'link' => ['uri' => 'internal:' . $path]]);
      $link->save();
    }
  }
  \Drupal::state()->set('club_public.menus_seeded', TRUE);
}
catch (\Throwable $e) {
  $transaction->rollBack();
  throw $e;
}
