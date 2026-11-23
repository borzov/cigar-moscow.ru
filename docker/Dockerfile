FROM drupal:11.4-php8.5-apache
RUN apt-get update && apt-get install -y --no-install-recommends default-mysql-client git unzip \
    && rm -rf /var/lib/apt/lists/*
ENV COMPOSER_ALLOW_SUPERUSER=1
RUN echo "opcache.revalidate_freq=0" > /usr/local/etc/php/conf.d/zz-club-development.ini
