<?php

namespace Drupal\club_public\Controller;

use Drupal\Core\Cache\CacheableMetadata;
use Drupal\Core\Controller\ControllerBase;
use Drupal\Core\Entity\Query\QueryInterface;
use Drupal\Core\Link;
use Drupal\club_forms\RegistrationWindow;
use Drupal\node\NodeInterface;
use Drupal\taxonomy\TermInterface;
use Symfony\Component\HttpKernel\Exception\NotFoundHttpException;

/**
 * Public club catalogue built from published default revisions.
 */
final class Catalogue extends ControllerBase {

  private const PAGE_SIZE = 12;
  private CacheableMetadata $metadata;

  public function __construct() {
    $this->metadata = (new CacheableMetadata())
      ->setCacheTags(['node_list', 'taxonomy_term_list:club_rubrics', 'path_alias_list'])
      ->setCacheContexts(['languages:language_content', 'languages:language_interface', 'languages:language_url', 'user.node_grants:view', 'user.permissions', 'url.query_args:page']);
  }

  public function home(): array {
    $cover = $this->page('/home-cover');
    $hero = ['#theme' => 'club_hero', '#title' => $cover?->label() ?? 'Московский сигарный клуб'];
    if ($cover) {
      $hero['#cover'] = $this->cover($cover);
      $hero['#body'] = $cover->get('body')->view(['label' => 'hidden']);
    }
    $festival = $this->promotedFestival();
    if ($festival) {
      $build['season'] = $this->feature($festival, TRUE);
      $build['season']['#cover'] ??= $hero['#cover'] ?? NULL;
    }
    else {
      $build['hero'] = $hero;
    }
    $build['tastings'] = $this->section('Свежие дегустации', $this->rows($this->byDate('tasting'), 3), 'Пока нет опубликованных дегустаций.', $this->link('Все дегустации', 'tastings'));
    $build['rating'] = $this->section('Клубный рейтинг', $this->ranking(3), 'Пока нет клубных оценок.', $this->link('Весь рейтинг', 'rating'));
    $build['upcoming'] = $this->section('Ближайшие события', $this->rows($this->calendarQuery('event', TRUE), 3), 'Новые даты пока не объявлены.', $this->link('Календарь событий', 'events'));
    $build['festivals'] = $this->section('Мировые фестивали и поездки', $this->rows($this->byDate('event')->condition('field_event_type', 'world_festival'), 3), '', $this->link('Все поездки', 'travel'));
    $build['journal'] = $this->section('Журнал', $this->rows($this->query('journal')->sort('created', 'DESC'), 3), 'Материалы готовятся к публикации.', $this->link('Все материалы', 'journal'));
    $build['club'] = $this->clubLinks('Клуб', ['/club/awards', '/club/partners'], summaries: TRUE);
    return $this->finish($build, TRUE);
  }

  public function events(): array {
    $build['upcoming'] = $this->section('Календарь', $this->rows($this->calendarQuery('event', TRUE)), 'Ближайшие даты пока не объявлены.');
    $build['pager'] = ['#type' => 'pager'];
    $build['links'] = ['#theme' => 'item_list', '#items' => [$this->link('Архив событий', 'archive'), $this->link('Мировые фестивали и поездки', 'travel'), $this->link('Фотоальбомы', 'gallery')]];
    return $this->finish($build, TRUE);
  }

  public function festivals(): array {
    $build = [];
    $next = $this->nodes($this->calendarQuery('festival', TRUE)->sort('nid')->range(0, 1)->execute())->current();
    if ($next) {
      $build['next'] = $this->feature($next);
      $others = $this->rows($this->calendarQuery('festival', TRUE)->condition('nid', $next->id(), '<>'), -1);
      if ($others) {
        $build['calendar'] = $this->section('Следующие выпуски', $others);
      }
    }
    else {
      $build['next'] = $this->section('Ближайший фестиваль', [], 'Новые даты пока не объявлены.');
    }
    $build['editions'] = $this->section('Архив фестиваля', $this->rows($this->calendarQuery('festival', FALSE)), 'В архиве пока нет выпусков.');
    $build['pager'] = ['#type' => 'pager'];
    $build['travel'] = $this->link('Мировые фестивали и поездки', 'travel');
    return $this->finish($build, TRUE);
  }

  public function listing(string $section): array {
    $query = match ($section) {
      'cigars' => $this->query('cigar')->sort('title'),
      'tastings' => $this->byDate('tasting'),
      'journal' => $this->query('journal')->sort('created', 'DESC'),
      'gallery' => $this->byDate('album'),
      'pairings' => $this->query('journal')->condition('field_rubrics', $this->pairingIds() ?: [0], 'IN')->sort('created', 'DESC'),
      'archive' => $this->calendarQuery('event', FALSE),
      'travel' => $this->byDate('event')->condition('field_event_type', 'world_festival'),
    };
    if ($section === 'cigars') {
      $build['links'] = ['#theme' => 'item_list', '#items' => [$this->link('Клубный рейтинг', 'rating'), $this->link('Все дегустации', 'tastings'), $this->link('Сигарные сочетания', 'pairings')]];
    }
    if ($section === 'journal' || $section === 'pairings') {
      $build['rubrics'] = $this->rubricLinks($section === 'pairings');
    }
    $build['list'] = $this->section(NULL, $this->rows($query), 'Здесь пока нет опубликованных материалов.');
    $build['pager'] = ['#type' => 'pager'];
    return $this->finish($build, $section === 'archive');
  }

  private function pairingIds(): array {
    return $this->entityTypeManager()->getStorage('taxonomy_term')->getQuery()
      ->accessCheck(TRUE)->condition('vid', 'club_rubrics')->condition('status', 1)
      ->condition('field_slug', 'pairing_', 'STARTS_WITH')->execute();
  }

  private function rubricTerm(string $slug): TermInterface {
    $storage = $this->entityTypeManager()->getStorage('taxonomy_term');
    $query = $storage->getQuery()->accessCheck(TRUE)->condition('vid', 'club_rubrics')->condition('status', 1);
    $ids = $query->condition($query->orConditionGroup()->condition('field_slug', $slug)->condition('uuid', $slug))
      ->range(0, 1)->execute();
    $term = $ids ? $storage->load(reset($ids)) : NULL;
    if (!$term || !$term->access('view')) {
      throw new NotFoundHttpException();
    }
    return $term;
  }

  public function rubricTitle(string $rubric): string {
    return $this->rubricTerm($rubric)->label();
  }

  public function rubric(string $rubric): array {
    $term = $this->rubricTerm($rubric);
    $this->metadata->addCacheableDependency($term)->addCacheableDependency($term->access('view', NULL, TRUE));
    $q = $this->query('journal')->condition('field_rubrics', $term->id())->sort('created', 'DESC');
    $build['list'] = $this->section(NULL, $this->rows($q), 'Материалы этой рубрики пока не опубликованы.', $this->link('Весь журнал', 'journal'));
    $build['pager'] = ['#type' => 'pager'];
    return $this->finish($build);
  }

  private function rubricLinks(bool $pairings): array {
    $query = $this->entityTypeManager()->getStorage('node')->getAggregateQuery()
      ->accessCheck(TRUE)->condition('type', 'journal')->condition('status', 1)->groupBy('field_rubrics');
    $ids = array_column($query->execute(), 'field_rubrics_target_id');
    $terms = $this->entityTypeManager()->getStorage('taxonomy_term')->loadMultiple(array_filter($ids));
    $links = [];
    foreach ($terms as $term) {
      $key = $term->get('field_slug')->value ?: $term->uuid();
      $access = $term->access('view', NULL, TRUE);
      $this->metadata->addCacheableDependency($term)->addCacheableDependency($access);
      if ($key && $term->isPublished() && $access->isAllowed() && (!$pairings || str_starts_with($key, 'pairing_'))) {
        $links[] = Link::createFromRoute($term->label(), 'club_public.rubric', ['rubric' => $key])->toRenderable();
      }
    }
    if (!$pairings) {
      $links[] = $this->link('Все сигарные сочетания', 'pairings');
    }
    return ['#theme' => 'item_list', '#items' => $links];
  }

  public function rating(): array {
    $build['rule'] = ['#plain_text' => 'Предварительное правило рейтинга: для каждой сигары берётся клубная оценка последней датированной опубликованной дегустации с коллективной оценкой. При совпадении дат используется запись с большим номером.'];
    $build['list'] = $this->section(NULL, $this->ranking(), 'Пока нет опубликованных клубных оценок.');
    $build['pager'] = ['#type' => 'pager'];
    return $this->finish($build);
  }

  public function related(NodeInterface $node): array {
    if ($node->bundle() === 'club_page') {
      $en = $node->language()->getId() === 'en';
      return $this->finish($this->clubLinks($en ? 'Club' : 'О клубе', $en ? ['/club', '/contacts'] : ['/club', '/club/history', '/club/board', '/club/traditions', '/club/awards', '/club/partners', '/club/invitation', '/club/terms', '/contacts'], $node->id()));
    }
    $build = [];
    $id = $node->id();
    $relations = match ($node->bundle()) {
      'cigar' => [['tasting', 'field_cigar', 'Дегустации'], ['journal', 'field_cigars', 'В журнале']],
      'event' => [['tasting', 'field_event', 'Дегустации'], ['journal', 'field_event', 'Материалы'], ['album', 'field_event', 'Фотоальбомы']],
      'festival' => [['event', 'field_festival', 'События фестиваля'], ['journal', 'field_festival', 'Материалы'], ['album', 'field_festival', 'Фотоальбомы']],
    };
    foreach ($relations as [$bundle, $field, $title]) {
      $query = $bundle === 'journal' ? $this->query($bundle)->sort('created', 'DESC') : $this->byDate($bundle);
      $rows = $this->rows($query->condition($field, $id), -1);
      if ($rows) {
        $build[$bundle] = $this->section($title, $rows);
      }
    }
    if ($node->bundle() === 'festival' && $node->isPublished()) {
      $build['registration'] = $this->registration($node) ?? [];
    }
    return $this->finish($build, $node->bundle() === 'festival');
  }

  private function query(string $bundle): QueryInterface {
    return $this->entityTypeManager()->getStorage('node')->getQuery()
      ->accessCheck(TRUE)->condition('type', $bundle)->condition('status', 1);
  }

  private function byDate(string $bundle): QueryInterface {
    return $this->query($bundle)->sort('field_date', 'DESC');
  }

  private function today(): string {
    $zone = $this->config('system.date')->get('timezone.default') ?: 'Europe/Moscow';
    $now = new \DateTimeImmutable('@' . \Drupal::time()->getRequestTime());
    return $now->setTimezone(new \DateTimeZone($zone))->format('Y-m-d');
  }

  private function calendarQuery(string $bundle, bool $upcoming): QueryInterface {
    $today = $this->today();
    $cmp = $upcoming ? '>=' : '<';
    $q = $this->query($bundle);
    // A multi-day event remains in the calendar through its last day.
    $dates = $q->orConditionGroup()->condition('field_end', $today, $cmp)
      ->condition($q->andConditionGroup()->notExists('field_end')->condition('field_date', $today, $cmp));
    return $q->condition($dates)->sort('field_date', $upcoming ? 'ASC' : 'DESC');
  }

  private function promotedFestival(): ?NodeInterface {
    $today = $this->today();
    $q = $this->query('festival');
    $active = $q->orConditionGroup()->condition('field_end', $today, '>=')
      ->condition($q->andConditionGroup()->notExists('field_end')->condition('field_date', $today, '>='));
    $q->condition($active)->condition('field_promote', $today, '<=')->sort('field_date')->sort('nid');
    foreach ($this->nodes($q->execute()) as $node) {
      return $node;
    }
    return NULL;
  }

  private function registration(NodeInterface $node): ?array {
    if (!RegistrationWindow::isOpen($node)) {
      return NULL;
    }
    return Link::createFromRoute('Регистрация на фестиваль', 'club_forms.festival', ['node' => $node->id()])->toRenderable();
  }

  private function feature(NodeInterface $node, bool $hero = FALSE): array {
    $date = $node->get('field_date')->value;
    $days = (int) (new \DateTimeImmutable($this->today()))->diff(new \DateTimeImmutable($date))->format('%r%a');
    return ['#theme' => 'club_feature', '#hero' => $hero, '#cover' => $this->cover($node), '#label' => 'Ближайший фестиваль', '#link' => $node->toLink()->toRenderable(), '#date' => $date, '#days' => $days, '#registration' => $this->registration($node)];
  }

  private function rows(QueryInterface $query, ?int $limit = NULL): array {
    $query->sort('nid', 'DESC');
    if ($limit === NULL) {
      $query->pager(self::PAGE_SIZE);
    }
    elseif ($limit >= 0) {
      $query->range(0, $limit);
    }
    $rows = [];
    foreach ($this->nodes($query->execute()) as $node) {
      $rows[] = [
        'link' => $node->toLink()->toRenderable(),
        'date' => $node->hasField('field_date') ? $node->get('field_date')->value : NULL,
        'cover' => $this->cover($node),
        'demo' => (bool) $node->get('field_demo')->value,
        'score' => $node->bundle() === 'tasting' ? $node->get('field_club_score')->value : NULL,
      ];
    }
    return $rows;
  }

  private function cover(NodeInterface $node): ?array {
    $field = $node->get('field_cover');
    $media = $field->entity;
    if (!$media) {
      return NULL;
    }
    $access = $media->access('view', NULL, TRUE);
    $this->metadata->addCacheableDependency($media)->addCacheableDependency($access);
    if (!$media->isPublished() || !$access->isAllowed()) {
      return NULL;
    }
    $image = $media->getSource()->getConfiguration()['source_field'];
    return [
      '#theme' => 'club_picture',
      '#image' => $media->get($image)->view(['label' => 'hidden', 'type' => 'image', 'settings' => ['image_style' => 'large']]),
      '#caption' => $media->label(),
      '#credit' => $media->get('field_credit')->value,
    ];
  }

  private function ranking(?int $limit = NULL): array {
    $q = $this->byDate('tasting')->exists('field_date')->exists('field_cigar')->exists('field_club_score')->sort('nid', 'DESC');
    $scores = [];
    foreach ($this->nodes($q->execute()) as $tasting) {
      $id = $tasting->get('field_cigar')->target_id;
      $scores[$id] ??= ['score' => (int) $tasting->get('field_club_score')->value, 'tasting' => $tasting];
    }
    $ranked = [];
    foreach ($this->nodes(array_keys($scores)) as $cigar) {
      $entry = $scores[$cigar->id()];
      $ranked[] = [
        'score' => $entry['score'],
        'link' => $cigar->toLink()->toRenderable(),
        'source' => $entry['tasting']->toLink()->toRenderable(),
        'id' => (int) $cigar->id(),
      ];
    }
    usort($ranked, static fn(array $a, array $b): int => $b['score'] <=> $a['score'] ?: $a['id'] <=> $b['id']);
    if ($limit !== NULL) {
      return array_slice($ranked, 0, $limit);
    }
    $pager = \Drupal::service('pager.manager')->createPager(count($ranked), self::PAGE_SIZE);
    return array_slice($ranked, $pager->getCurrentPage() * self::PAGE_SIZE, self::PAGE_SIZE);
  }

  private function nodes(array $ids): \Generator {
    $storage = $this->entityTypeManager()->getStorage('node');
    foreach (array_chunk($ids, 100) as $batch) {
      foreach ($storage->loadMultiple($batch) as $node) {
        $node = \Drupal::service('entity.repository')->getTranslationFromContext($node);
        $access = $node->access('view', NULL, TRUE);
        $this->metadata->addCacheableDependency($access)->addCacheableDependency($node);
        if ($node->isPublished() && $access->isAllowed()) {
          yield $node;
        }
      }
    }
  }

  private function page(string $alias): ?NodeInterface {
    $path = \Drupal::service('path_alias.manager')->getPathByAlias($alias, 'ru');
    if (preg_match('~^/node/(\d+)$~D', $path, $match)) {
      return $this->nodes([$match[1]])->current();
    }
    return NULL;
  }

  private function clubLinks(string $title, array $paths, ?string $exclude = NULL, bool $summaries = FALSE): array {
    $rows = [];
    foreach ($paths as $path) {
      $page = $this->page($path);
      if ($page && $page->id() !== $exclude) {
        $row = ['link' => $page->toLink()->toRenderable()];
        if ($summaries) {
          $row['summary'] = $page->get('body')->view(['label' => 'hidden', 'type' => 'text_summary_or_trimmed', 'settings' => ['trim_length' => 240]]);
        }
        $rows[] = $row;
      }
    }
    return $rows ? $this->section($title, $rows) : [];
  }

  private function link(string $label, string $route): array {
    return Link::createFromRoute($label, 'club_public.' . $route)->toRenderable();
  }

  private function section(?string $title, array $rows, string $empty = '', ?array $more = NULL): array {
    return ['#theme' => 'club_section', '#title' => $title, '#rows' => $rows, '#empty' => $empty, '#more' => $more];
  }

  private function finish(array $build, bool $timeSensitive = FALSE): array {
    if ($timeSensitive) {
      // Also bypass anonymous page caching when a festival detail is rendered.
      \Drupal::service('page_cache_kill_switch')->trigger();
      $this->metadata->setCacheMaxAge(0);
    }
    $this->metadata->applyTo($build);
    return $build;
  }

}
