<?php

namespace Drupal\club_public\EventSubscriber;

use Drupal\Core\Language\LanguageInterface;
use Drupal\Core\Language\LanguageManagerInterface;
use Drupal\Core\Routing\LocalRedirectResponse;
use Drupal\Core\Routing\RouteMatch;
use Drupal\Core\Url;
use Drupal\node\NodeInterface;
use Symfony\Component\EventDispatcher\EventSubscriberInterface;
use Symfony\Component\HttpKernel\Event\RequestEvent;
use Symfony\Component\HttpKernel\KernelEvents;

/**
 * Sends English archive requests to their published canonical language.
 */
final class PublicLanguageSubscriber implements EventSubscriberInterface {

  public function __construct(private readonly LanguageManagerInterface $languages) {}

  public static function getSubscribedEvents(): array {
    // Run after routing has resolved aliases, access and converted entities.
    return [KernelEvents::REQUEST => ['onRequest', 25]];
  }

  public static function russianRoute(string $route): bool {
    return str_starts_with($route, 'club_public.') || $route === 'club_forms.festival';
  }

  public function onRequest(RequestEvent $event): void {
    $request = $event->getRequest();
    if (!$event->isMainRequest() || !in_array($request->getMethod(), ['GET', 'HEAD'], TRUE)
      || $this->languages->getCurrentLanguage(LanguageInterface::TYPE_URL)->getId() !== 'en') {
      return;
    }
    $route = RouteMatch::createFromRequest($request);
    $name = $route->getRouteName() ?? '';
    $node = $route->getParameter('node');
    $options = ['language' => $this->languages->getLanguage('ru'), 'query' => $request->query->all()];
    if ($name === 'club_public.home') {
      $options['language'] = $this->languages->getLanguage('en');
      $url = Url::fromUserInput('/club', $options);
    }
    elseif (self::russianRoute($name)) {
      $url = Url::fromRoute($name, $route->getRawParameters()->all(), $options);
    }
    elseif ($name === 'entity.node.canonical' && $node instanceof NodeInterface && (!$node->hasTranslation('en') || !$node->getTranslation('en')->isPublished())) {
      $url = $node->toUrl('canonical', $options);
    }
    else {
      return;
    }

    $generated = $url->toString(TRUE);
    $response = new LocalRedirectResponse($generated->getGeneratedUrl(), 302);
    $response->addCacheableDependency($generated);
    if ($node instanceof NodeInterface) {
      $response->addCacheableDependency($node);
    }
    $response->getCacheableMetadata()->addCacheTags(['path_alias_list'])->addCacheContexts(['url']);
    $event->setResponse($response);
  }

}
