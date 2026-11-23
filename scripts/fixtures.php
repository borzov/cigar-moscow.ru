<?php

/**
 * @file
 * Seeds linked examples. A second run preserves the editor's changes.
 */

use Drupal\Core\File\FileExists;
use Drupal\Core\File\FileSystemInterface;
use Drupal\media\Entity\Media;
use Drupal\node\Entity\Node;
use Drupal\node\NodeInterface;
use Drupal\path_alias\Entity\PathAlias;
use Drupal\taxonomy\Entity\Term;

$entities = \Drupal::entityTypeManager();
$node_storage = $entities->getStorage('node');
$alias_storage = $entities->getStorage('path_alias');
$alias = static function (NodeInterface $node, string $path, string $langcode) use ($alias_storage): void {
  $existing = $alias_storage->loadByProperties(['alias' => $path, 'langcode' => $langcode]);
  $system_path = '/node/' . $node->id();
  if ($existing) {
    if (reset($existing)->getPath() !== $system_path) {
      throw new RuntimeException("Alias $path ($langcode) already belongs to another page.");
    }
    return;
  }
  PathAlias::create(['path' => $system_path, 'alias' => $path, 'langcode' => $langcode])->save();
};
$body = static fn (string $html): array => ['value' => $html, 'format' => 'basic_html'];
$seed = static function (string $bundle, string $key, string $path, string $title, string $html, array $fields = []) use ($node_storage, $body, $alias): NodeInterface {
  $source_id = 'demo:' . $key;
  $matches = $node_storage->loadByProperties(['type' => $bundle, 'field_source_id' => $source_id]);
  $node = reset($matches);
  if (!$node) {
    $node = Node::create($fields + [
      'type' => $bundle, 'langcode' => 'ru', 'title' => $title, 'body' => $body($html),
      'uid' => 1, 'moderation_state' => 'published', 'field_source_id' => $source_id,
      'path' => ['pathauto' => 0],
      'field_demo' => TRUE, 'promote' => FALSE,
    ]);
    $node->save();
  }
  $alias($node, $path, 'ru');
  return $node;
};
$translate = static function (NodeInterface $node, string $path, string $title, string $html) use ($body, $alias): void {
  if (!$node->hasTranslation('en')) {
    $node->addTranslation('en', [
      'title' => $title,
      'body' => $body($html),
      'moderation_state' => 'published',
      'content_translation_source' => 'ru',
      'path' => ['pathauto' => 0],
    ])->save();
  }
  $alias($node, $path, 'en');
};

$media_storage = $entities->getStorage('media');
$archive_url = 'https://www.cigar-moscow.ru/cigar_news.html?item_id=886';
$photo = static function (string $filename, string $uuid, string $caption) use ($media_storage, $archive_url): Media {
  $existing = $media_storage->loadByProperties(['uuid' => $uuid]);
  if ($existing) {
    return reset($existing);
  }
  $source = dirname(\Drupal::root()) . '/scripts/assets/' . $filename;
  if (!is_readable($source)) {
    throw new RuntimeException("Missing club archive photograph: $filename");
  }
  $directory = 'public://club-archive';
  \Drupal::service('file_system')->prepareDirectory($directory, FileSystemInterface::CREATE_DIRECTORY);
  $file = \Drupal::service('file.repository')->writeData(
    file_get_contents($source), "$directory/$filename", FileExists::Replace,
  );
  $dimensions = getimagesize($source);
  $media = Media::create([
    'bundle' => 'image', 'uuid' => $uuid, 'name' => $caption, 'langcode' => 'ru',
    'uid' => 1, 'status' => 1,
    'field_media_image' => [
      'target_id' => $file->id(), 'alt' => $caption,
      'width' => $dimensions[0], 'height' => $dimensions[1],
    ],
    'field_credit' => 'Фотоархив Московских Афисионадо',
    'field_legacy_url' => ['uri' => $archive_url],
  ]);
  $media->save();
  return $media;
};
$cover = $photo('club-archive.jpg', '15cb19f9-8fb3-4ebd-8260-1dfb45f9ce91', 'Участники первого вечера MA Cigar Fest 2016');

$evening = $photo('club-evening.jpg', '37c176a6-d40d-42ed-96b6-2bac7856694c', 'Выступление на первом вечере MA Cigar Fest 2016');

$seed('club_page', 'cover', '/home-cover', 'Первый вечер MA Cigar Fest 2016',
  '<p>Участники первого вечера фестиваля на снимке из фотоархива Московских Афисионадо.</p>',
  ['field_cover' => $cover->id(), 'field_legacy_url' => ['uri' => $archive_url]]);
$club = $seed('club_page', 'club', '/club', 'Московские Афисионадо',
  '<p>Клуб «Московские Афисионадо» основан в 2010 году. Здесь собраны его история, традиции и материалы встреч. В открытом каталоге можно перейти от события к записям дегустации и фотографиям.</p>');
$translate($club, '/club', 'Moscow Aficionados',
  '<p>Moscow Aficionados was founded in 2010. Explore the club calendar, tasting notes and photographs from past gatherings.</p>
  <p><a href="/en/contacts">Contact the club</a></p>');
$contacts = $seed('club_page', 'contacts', '/contacts', 'Контакты',
  '<p>Чтобы организаторы связались с вами по поводу участия, оставьте имя и электронную почту через <a href="/membership">форму обращения в клуб</a>. На локальном стенде организатор читает обращения в закрытом разделе. Используйте вымышленные контактные данные для проверки.</p>');
$translate($contacts, '/contacts', 'Contacts',
  '<p>For membership enquiries, use the <a href="/membership">club enquiry form in Russian</a>. This is a local preview. Please use fictional contact details when testing it.</p>');
$pages = [
  ['history', 'История клуба', '<p>Клуб «Московские Афисионадо» основан в 2010 году. В 2014 и 2022 годах он получил награду «Лучший сигарный клуб России». Один из документированных эпизодов — первый вечер MA Cigar Fest 2016.</p><p><a href="' . $archive_url . '">Фотографии в прежнем архиве клуба</a></p>'],
  ['board', 'Президиум', '<p>На этой странице редакция сможет представить членов Президиума клуба и их обязанности. В демонстрационном выпуске персональный состав не публикуется.</p>'],
  ['traditions', 'Традиции', '<p>Один из способов вести дневник дегустаций — записывать впечатления по третям. В каталоге есть <a href="/tastings/demo-session">образец такого протокола</a>.</p>'],
  ['awards', 'Награды', '<p>В 2014 и 2022 годах «Московские Афисионадо» получили награду «Лучший сигарный клуб России».</p>'],
  ['partners', 'Партнёры', '<p>Здесь редакция разместит сведения о подтверждённых партнёрах. По вопросам участия можно <a href="/contacts">связаться с организаторами</a>.</p>'],
  ['invitation', 'Приглашение в клуб', '<p>Для вступления в клуб нужна рекомендация. Если вы хотите уточнить порядок вступления, оставьте своё имя и электронную почту. Организаторы смогут связаться с вами.</p><p><a href="/membership">Обратиться в клуб</a></p>'],
  ['terms', 'Условия участия', '<p>Вступление в клуб возможно по рекомендации. Через форму можно оставить имя и электронную почту для связи с организаторами. Для фестиваля предусмотрена отдельная запись в сроки, указанные на странице выпуска. В локальной версии вы можете проверить обе формы на демонстрационных данных.</p>'],
];
foreach ($pages as [$key, $title, $html]) {
  $seed('club_page', $key, '/club/' . $key, $title, $html);
}
$seed('club_page', 'privacy', '/privacy', 'Согласие на обработку данных',
  '<p>Демонстрационная редакция для локального стенда. Используйте вымышленные данные.</p>
  <p>При отправке формы вы соглашаетесь на обработку имени, адреса электронной почты и, для регистрации, выбранного выпуска фестиваля. Организаторы используют их, чтобы ответить на вопрос о клубе или рассмотреть заявку на выбранный выпуск фестиваля.</p>
  <p>К обращениям имеют доступ уполномоченные сотрудники. Срок хранения — 90 дней. Сведения об операторе, контакт для отзыва согласия и окончательную редакцию условий владелец сайта должен заполнить до публичного запуска.</p>');

// Seed identities survive label changes and independent installations.
$term_storage = $entities->getStorage('taxonomy_term');
$seed_term = static function (string $vocabulary, string $key, string $label) use ($term_storage): Term {
  $identity = ['vid' => $vocabulary];
  $identity[$vocabulary === 'club_rubrics' ? 'field_slug' : 'uuid'] = $key;
  $terms = $term_storage->loadByProperties($identity);
  if ($terms) {
    return reset($terms);
  }
  $term = Term::create($identity + ['langcode' => 'ru', 'name' => $label]);
  $term->save();
  return $term;
};
$brand = $seed_term('club_brands', '37c0d574-aae7-5e12-ac90-ac78a7a4a1c1', 'Демонстрационная марка');
$nicaragua = $seed_term('club_countries', '0a4a49aa-5e98-5b95-b575-0e4eb6227531', 'Никарагуа');
$dominican = $seed_term('club_countries', 'd4d00281-da5c-55f3-bb93-6660ddbe8113', 'Доминиканская Республика');
$rubrics = [];
foreach ([
  'club' => 'Клубная жизнь', 'interview' => 'Интервью', 'digest' => 'Дайджест',
  'portrait' => 'Портрет', 'travel' => 'Путешествия', 'vintage' => 'Винтаж',
  'humidor' => 'Хьюмидор', 'guide' => 'Путеводитель',
  'pairing_cigar' => 'Сигарные сочетания', 'pairing_tea' => 'Сигара и чай',
  'pairing_drink' => 'Сигара и напиток',
] as $key => $label) {
  $rubrics[$key] = $seed_term('club_rubrics', $key, $label);
}

$cigar = $seed('cigar', 'cigar-main', '/cigars/demo-edition', 'Robusto № 1 · образец',
  '<p>Учебная карточка каталога. Марка и серия вымышлены. Связанные дегустации показывают, как меняется описание одной и той же сигары от встречи к встрече.</p>',
  ['field_brand_term' => $brand->id(), 'field_format' => 'Robusto',
    'field_country_term' => $nicaragua->id(), 'field_edition' => 'Учебная серия, выпуск 1']);
$second_cigar = $seed('cigar', 'cigar-second', '/cigars/demo-corona', 'Corona № 2 · образец',
  '<p>Второй условный образец для сравнения форматов и проверки клубного рейтинга. Значения внесены для локальной демонстрации.</p>',
  ['field_brand_term' => $brand->id(), 'field_format' => 'Corona',
    'field_country_term' => $dominican->id(), 'field_edition' => 'Учебная серия, выпуск 2']);

$festival = $seed('festival', 'festival-edition', '/festivals/demo-edition', 'Фестиваль · архивный образец',
  '<p>Учебный выпуск ежегодного фестиваля. Календарные даты и программа условны.</p>',
  ['field_year' => 2000, 'field_date' => '2000-09-15', 'field_end' => '2000-09-17',
    'field_promote' => '2000-08-15', 'field_reg_start' => '2000-08-20', 'field_reg_end' => '2000-09-14',
    'field_program' => $body('<ol><li>Встреча гостей и знакомство с программой.</li><li>Обсуждение двух форматов и запись дегустационных заметок.</li><li>Круглый стол и общий альбом.</li></ol>')]);
$today = new DateTimeImmutable('today', new DateTimeZone('Europe/Moscow'));
$relative = static fn (string $offset): string => $today->modify($offset)->format('Y-m-d');
$seed('festival', 'festival-upcoming', '/festivals/demo-upcoming', 'Фестиваль · демонстрационная регистрация',
  '<p>Учебный выпуск для проверки регистрации и календаря. Даты отсчитываются от первого запуска стенда. Используйте вымышленные имя и электронную почту.</p>',
  ['field_year' => (int) $today->modify('+30 days')->format('Y'), 'field_date' => $relative('+30 days'), 'field_end' => $relative('+32 days'),
    'field_promote' => $relative('-15 days'), 'field_reg_start' => $relative('-7 days'), 'field_reg_end' => $relative('+24 days'),
    'field_program' => $body('<ol><li>Открытие и знакомство.</li><li>Клубная дегустация.</li><li>Подведение итогов.</li></ol>')]);
$event = $seed('event', 'event-evening', '/events/demo-club-evening', 'Клубный вечер · образец',
  '<p>Учебная запись завершённой встречи. В программе — два образца, обсуждение третьей части протокола и подбор чая.</p>',
  ['field_date' => '2000-09-16', 'field_event_type' => 'club', 'field_festival' => $festival->id()]);
$seed('event', 'event-world', '/events/demo-world-festival', 'Фестивальная поездка · образец',
  '<p>Пример внешнего события в календаре поездок. Место, организаторы и реальный фестиваль не указываются.</p>',
  ['field_date' => '2000-10-07', 'field_end' => '2000-10-09', 'field_event_type' => 'world_festival']);
$seed('event', 'event-upcoming', '/events/demo-calendar', 'Предстоящая встреча · образец',
  '<p>Так выглядит анонс в календаре. Дата назначена относительно установки стенда. Это учебная встреча без записи гостей.</p>',
  ['field_date' => $relative('+35 days'), 'field_event_type' => 'club']);

$seed('tasting', 'tasting-main', '/tastings/demo-session', 'Robusto № 1 · общий прокур, образец',
  '<p>Пример сопоставления общего результата и записи одного участника. Все баллы и дегустационные заметки в этом протоколе вымышлены.</p>',
  ['field_cigar' => $cigar->id(), 'field_event' => $event->id(), 'field_date' => '2000-09-16',
    'field_third_first' => 'Сухая древесина, лёгкая пряность.', 'field_third_second' => 'Какао и поджаренный орех.',
    'field_third_last' => 'Перец и более плотный древесный тон.', 'field_club_score' => 86,
    'field_individual_score' => 82, 'field_score_original' => '86/100, условный протокол']);
$seed('tasting', 'tasting-second', '/tastings/demo-corona', 'Corona № 2 · клубный прокур, образец',
  '<p>Вымышленный результат второго образца той же встречи. Учебные баллы нужны для проверки сортировки рейтинга.</p>',
  ['field_cigar' => $second_cigar->id(), 'field_event' => $event->id(), 'field_date' => '2000-09-16',
    'field_third_first' => 'Цедра и сено.', 'field_third_second' => 'Сладкая пряность.',
    'field_third_last' => 'Короткое ореховое послевкусие.', 'field_club_score' => 89]);
$seed('tasting', 'tasting-personal', '/tastings/demo-personal', 'Robusto № 1 · личная запись, образец',
  '<p>Пример самостоятельной дегустации без общего клубного результата. Записанные впечатления и оценка условны.</p>',
  ['field_cigar' => $cigar->id(), 'field_date' => '2000-10-01', 'field_individual_score' => 84,
    'field_third_first' => 'В начале выделяется кедр.', 'field_third_second' => 'Мягкий ореховый оттенок.',
    'field_third_last' => 'Продолжительное пряное послевкусие.']);

$seed('journal', 'journal-tea', '/journal/demo-tea', 'Сигара и чай · редакционный образец',
  '<p>Условная запись с дегустационного стола. В первом сравнении заварили один чай дважды и описали, как крепость настоя меняет восприятие древесной ноты. Для второго взяли другой формат сигары, сохранив температуру воды.</p>',
  ['field_rubrics' => [$rubrics['pairing_tea']->id()], 'field_cigars' => [$cigar->id(), $second_cigar->id()],
    'field_event' => $event->id(), 'field_festival' => $festival->id()]);
$seed('album', 'album-evening', '/albums/demo-evening', 'Альбом клубной встречи · образец',
  '<p>Пример альбома, связанного с учебной встречей и учебным выпуском фестиваля. Фотографии взяты из архива MA Cigar Fest 2016, дата альбома относится к учебному примеру.</p>',
  ['field_date' => '2000-09-16', 'field_cover' => $cover->id(), 'field_images' => [$cover->id(), $evening->id()],
    'field_event' => $event->id(), 'field_festival' => $festival->id()]);
print "Club sample pages and linked editorial records are present.\n";
