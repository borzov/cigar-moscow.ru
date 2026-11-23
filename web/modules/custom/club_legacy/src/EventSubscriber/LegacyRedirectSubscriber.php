<?php

namespace Drupal\club_legacy\EventSubscriber;

use Drupal\club_legacy\LegacySource;
use Drupal\Core\Entity\EntityRepositoryInterface;
use Drupal\Core\KeyValueStore\KeyValueFactoryInterface;
use Drupal\Core\PageCache\ResponsePolicy\KillSwitch;
use Drupal\Core\Routing\LocalRedirectResponse;
use Drupal\Core\Session\AnonymousUserSession;
use Drupal\node\NodeInterface;
use Symfony\Component\EventDispatcher\EventSubscriberInterface;
use Symfony\Component\HttpFoundation\Response;
use Symfony\Component\HttpKernel\Event\ExceptionEvent;
use Symfony\Component\HttpKernel\Exception\NotFoundHttpException;
use Symfony\Component\HttpKernel\KernelEvents;

/**
 * Resolves migrated archive addresses after Drupal's normal route lookup.
 */
final class LegacyRedirectSubscriber implements EventSubscriberInterface {

  public function __construct(
    private readonly KeyValueFactoryInterface $keyValue,
    private readonly EntityRepositoryInterface $entities,
    private readonly KillSwitch $cacheKillSwitch,
  ) {}

  /**
   * {@inheritdoc}
   */
  public static function getSubscribedEvents(): array {
    // Handle archive URLs before Drupal renders its standard 404 response.
    return [KernelEvents::EXCEPTION => ['onNotFound', 210]];
  }

  /**
   * Redirects an explicitly mapped URL when its destination is still public.
   */
  public function onNotFound(ExceptionEvent $event): void {
    $request = $event->getRequest();
    if (!$event->isMainRequest() || !$event->getThrowable() instanceof NotFoundHttpException
      || !in_array($request->getMethod(), ['GET', 'HEAD'], TRUE)) {
      return;
    }
    $key = LegacySource::key($request->getPathInfo() . '?' . $request->server->get('QUERY_STRING', ''));
    if ($key === NULL) {
      return;
    }
    $uuid = $this->keyValue->get(LegacySource::COLLECTION)->get($key);
    if ($uuid === NULL) {
      return;
    }
    $this->cacheKillSwitch->trigger();
    $headers = ['Cache-Control' => 'private, no-store'];
    $node = $this->entities->loadEntityByUuid('node', $uuid);
    if (!$node instanceof NodeInterface || !$node->isPublished()
      || !$node->access('view', new AnonymousUserSession()) || !$node->access('view')) {
      $event->setResponse(new Response('Страница не найдена.', Response::HTTP_NOT_FOUND, $headers));
      return;
    }
    $target = $node->toUrl('canonical', ['language' => $node->language()])->toString();
    $event->setResponse(new LocalRedirectResponse($target, Response::HTTP_MOVED_PERMANENTLY, $headers));
  }

}
