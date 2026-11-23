<?php

namespace Drupal\Tests\club_forms\Functional;

use Drupal\field\Entity\FieldConfig;
use Drupal\field\Entity\FieldStorageConfig;
use Drupal\node\Entity\NodeType;
use Drupal\Tests\BrowserTestBase;
use PHPUnit\Framework\Attributes\Group;
use PHPUnit\Framework\Attributes\RunTestsInSeparateProcesses;

/**
 * Exercises public forms, retention and access to private submissions.
 */
#[Group('club_forms')]
#[RunTestsInSeparateProcesses]
final class ApplicationsTest extends BrowserTestBase {

  /**
   * {@inheritdoc}
   */
  protected static $modules = ['club_forms', 'page_cache', 'dynamic_page_cache'];

  /**
   * {@inheritdoc}
   */
  protected $defaultTheme = 'stark';

  /**
   * Tests consent, validation, private access and retention.
   */
  public function testMembership(): void {
    $this->drupalGet('admin/content/club-applications');
    $this->assertSession()->statusCodeEquals(403);
    $this->drupalGet('membership');
    $this->assertSession()->linkByHrefExists('/privacy');
    $this->assertSession()->checkboxNotChecked('consent');
    $values = ['applicant_name' => 'Тестовый участник', 'email' => 'example@example.test'];
    $this->submitForm($values, 'Отправить заявку');
    $this->assertSame(0, $this->submissionCount());
    $this->submitForm(['email' => 'invalid address', 'consent' => 1] + $values, 'Отправить заявку');
    $this->assertSame(0, $this->submissionCount());
    $this->submitForm($values + ['consent' => 1], 'Отправить заявку');
    $this->assertSession()->pageTextContains('Ваша заявка принята.');
    $this->assertSame(1, $this->submissionCount());
    $row = $this->container->get('database')->select('club_application', 'a')->fields('a')->execute()->fetchAssoc();
    $this->assertSame('membership', $row['kind']);
    $this->assertNull($row['festival_nid']);
    $this->assertSame('1', $row['consent_version']);
    $this->assertGreaterThan(0, (int) $row['consented']);
    $this->drupalLogin($this->drupalCreateUser(['access content']));
    $this->drupalGet('admin/content/club-applications');
    $this->assertSession()->statusCodeEquals(403);
    $this->drupalLogin($this->drupalCreateUser(['view private club applications']));
    $this->drupalGet('admin/content/club-applications');
    $this->assertSession()->statusCodeEquals(200);
    $this->assertSession()->pageTextContains($values['email']);
    $this->container->get('database')->update('club_application')->fields(['consented' => strtotime('-91 days')])->execute();
    $this->container->get('module_handler')->invoke('club_forms', 'cron');
    $this->assertSame(0, $this->submissionCount());
  }

  /**
   * Replaying a POST is idempotent; an independently rendered form is new.
   */
  public function testSubmissionReplay(): void {
    $values = ['applicant_name' => 'Участник', 'email' => 'example@example.test', 'consent' => 1];
    $this->drupalGet('membership');
    $client = $this->getSession()->getDriver()->getClient();
    $original = $client->getCrawler()->selectButton('Отправить заявку')->form($values);
    $this->drupalGet('membership');
    $second = $client->getCrawler()->selectButton('Отправить заявку')->form($values);
    $this->assertNotSame($original['form_build_id']->getValue(), $second['form_build_id']->getValue());
    $client->submit($original);
    $this->assertSame(1, $this->submissionCount());
    $client->submit($original);
    $this->assertSession()->pageTextContains('Ваша заявка принята.');
    $this->assertSame(1, $this->submissionCount());
    $client->submit($second);
    $this->assertSame(2, $this->submissionCount());
  }

  /**
   * Checks that repeated submissions from one address are limited.
   */
  public function testFloodLimit(): void {
    $values = ['applicant_name' => 'Участник', 'email' => 'example@example.test', 'consent' => 1];
    $this->drupalGet('membership');
    for ($i = 0; $i < 5; $i++) {
      $this->submitForm($values, 'Отправить заявку');
    }
    $this->assertSame(5, $this->submissionCount());
    $this->submitForm($values, 'Отправить заявку');
    $this->assertSession()->pageTextContains('Слишком много попыток.');
    $this->assertSame(5, $this->submissionCount());
  }

  /**
   * Tests registration on both date boundaries and after closure.
   */
  public function testFestivalRegistration(): void {
    NodeType::create(['type' => 'festival', 'name' => 'Фестиваль'])->save();
    foreach (['field_reg_start', 'field_reg_end'] as $field) {
      FieldStorageConfig::create([
        'entity_type' => 'node',
        'field_name' => $field,
        'type' => 'datetime',
        'settings' => ['datetime_type' => 'date'],
      ])->save();
      FieldConfig::create(['entity_type' => 'node', 'field_name' => $field, 'bundle' => 'festival'])->save();
    }
    $today = new \DateTimeImmutable('today', new \DateTimeZone('Europe/Moscow'));
    $date = $today->format('Y-m-d');
    $festival = $this->drupalCreateNode([
      'type' => 'festival',
      'title' => 'Тестовый фестиваль',
      'field_reg_start' => $date,
      'field_reg_end' => $date,
    ]);
    $path = 'festival/' . $festival->id() . '/register';
    $values = ['applicant_name' => 'Участник', 'email' => 'festival@example.test', 'consent' => 1];
    $this->drupalGet($path);
    $this->assertSession()->statusCodeEquals(200);
    $this->submitForm($values, 'Зарегистрироваться');
    $this->assertSame(1, $this->submissionCount());
    $row = $this->container->get('database')->select('club_application', 'a')->fields('a')->execute()->fetchAssoc();
    $this->assertSame('festival', $row['kind']);
    $this->assertEquals($festival->id(), $row['festival_nid']);
    // Submit the previously rendered form after an editor closes registration.
    $this->drupalGet($path);
    $festival->set('field_reg_end', $today->modify('-1 day')->format('Y-m-d'))->save();
    $this->submitForm($values, 'Зарегистрироваться');
    $this->assertSame(1, $this->submissionCount());
    $this->drupalGet($path);
    $this->assertSession()->statusCodeEquals(403);
    $festival->set('field_reg_start', $today->modify('+1 day')->format('Y-m-d'))->set('field_reg_end', $today->modify('+2 days')->format('Y-m-d'))->save();
    $this->drupalGet($path);
    $this->assertSession()->statusCodeEquals(403);
    $festival->set('field_reg_start', NULL)->save();
    $this->drupalGet($path);
    $this->assertSession()->statusCodeEquals(403);
    $festival->set('field_reg_start', $date)->setUnpublished()->save();
    $this->drupalGet($path);
    $this->assertSession()->statusCodeEquals(403);
  }

  /**
   * Counts records on the isolated test site.
   */
  private function submissionCount(): int {
    return (int) $this->container->get('database')->select('club_application')->countQuery()->execute()->fetchField();
  }

}
