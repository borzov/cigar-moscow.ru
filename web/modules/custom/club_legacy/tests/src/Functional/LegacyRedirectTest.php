<?php

namespace Drupal\Tests\club_legacy\Functional;

use Drupal\club_legacy\LegacySource;
use Drupal\node\Entity\NodeType;
use Drupal\path_alias\Entity\PathAlias;
use Drupal\Tests\BrowserTestBase;
use PHPUnit\Framework\Attributes\Group;
use PHPUnit\Framework\Attributes\RunTestsInSeparateProcesses;

/**
 * Tests pilot redirects using the exact URL patterns found in the archive.
 */
#[Group('club_legacy')]
#[RunTestsInSeparateProcesses]
final class LegacyRedirectTest extends BrowserTestBase {

  /**
   * {@inheritdoc}
   */
  protected static $modules = ['club_legacy', 'page_cache', 'dynamic_page_cache'];

  /**
   * {@inheritdoc}
   */
  protected $defaultTheme = 'stark';

  /**
   * Checks exact legacy URLs and the current status of their destinations.
   */
  public function testRedirects(): void {
    NodeType::create(['type' => 'festival', 'name' => 'Festival'])->save();
    $festival = $this->drupalCreateNode(['type' => 'festival']);
    $article = $this->drupalCreateNode(['type' => 'festival']);
    PathAlias::create(['path' => '/node/' . $festival->id(), 'alias' => '/festivals/edition'])->save();
    $alias = PathAlias::create(['path' => '/node/' . $article->id(), 'alias' => '/journal/report']);
    $alias->save();
    $redirects = $this->container->get('keyvalue')->get('club_legacy.redirects');
    $redirects->set('/news.html?category=27', $festival->uuid());
    $redirects->set('/cigar_news.html?item_id=886', $article->uuid());
    $redirects->set('/cigar_news.html?category=27&item_id=886', $article->uuid());
    $client = $this->getSession()->getDriver()->getClient();
    $client->followRedirects(FALSE);
    $this->checkRequest('GET', '/NEWS.html?CATEGORY=27', 301, '/festivals/edition');
    $redirects->set('/tasting.html?item_id=146', $article->uuid());
    $this->checkRequest('GET', '/tasting.html?item_id=146&yclid=123', 301, '/journal/report');
    $source = '/cigar_news.html?utm_source=archive&ITEM_ID=886&category=27';
    $this->checkRequest('GET', $source, 301, '/journal/report');
    $this->checkRequest('HEAD', '/cigar_news.html?item_id=886', 301, '/journal/report');
    foreach ([
      '/news.html',
      '/news.html?category=28',
      '/cigar_news.html?item_id=887',
      '/cigar_news.html?category=28&item_id=886',
      '/cigar_news.html?item_id=886&extra=1',
      '/cigar_news.html?item_id=887&item_id=886',
      '/anons.html?item_id=879',
      '/rating.html',
      '/tasting.html?category=27&item_id=146',
    ] as $unknown) {
      $this->checkRequest('GET', $unknown, 404);
    }
    $this->checkRequest('POST', '/news.html?category=27', 404);
    $this->checkRequest('GET', '/festivals/edition', 200);
    $alias->setAlias('/journal/updated-report')->save();
    $this->checkRequest('GET', $source, 301, '/journal/updated-report');
    $article->setUnpublished()->save();
    $this->checkRequest('GET', $source, 404);
    $this->assertSession()->responseNotContains('/journal/updated-report');
    $article->setPublished()->save();
    $this->checkRequest('GET', $source, 301, '/journal/updated-report');
  }

  /**
   * Checks the source-key contract shared by HTTP requests and the importer.
   */
  public function testSourceKeys(): void {
    $this->assertSame('/cigar_news.html?category=27&item_id=886', LegacySource::key('https://www.cigar-moscow.ru/Cigar_News.html?item_id=886&category=27&utm_campaign=test#read'));
    $this->assertSame('/news.html', LegacySource::key('/News.html?utm_source=archive'));
    $this->assertNotSame(LegacySource::key('/news.html'), LegacySource::key('/news.html?category=27'));
    $this->assertNull(LegacySource::key('https://other.example/news.html?category=27'));
    $this->assertNull(LegacySource::key('//other.example/news.html?category=27'));
  }

  /**
   * Issues the actual HTTP method and inspects the first response.
   */
  private function checkRequest(string $method, string $path, int $status, ?string $target = NULL): void {
    $client = $this->getSession()->getDriver()->getClient();
    $client->request($method, $this->baseUrl . $path);
    $response = $client->getInternalResponse();
    $this->assertSame($status, $response->getStatusCode(), $path);
    $this->assertSame($target, $response->getHeader('Location'), $path);
    if ($status === 301) {
      $this->assertMatchesRegularExpression('/no-store|no-cache/', $response->getHeader('Cache-Control'));
    }
  }

}
