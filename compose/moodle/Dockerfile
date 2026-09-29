# Build on the ARM64 Raspberry Pi. No development Moodle image is used.
FROM composer:2.10.3 AS composer
FROM php:8.3.33-apache-bookworm

ARG MOODLE_COMMIT=344232c15336c71b80f9aca8359ce0e0a9f3d116
LABEL org.opencontainers.image.title="Moodle 5.2.3 for Raspberry Pi" \
      org.opencontainers.image.source="https://github.com/moodle/moodle" \
      org.opencontainers.image.revision="344232c15336c71b80f9aca8359ce0e0a9f3d116"

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl git unzip util-linux \
      libicu-dev libpq-dev libzip-dev libpng-dev libjpeg62-turbo-dev \
      libfreetype6-dev libxml2-dev \
    && docker-php-ext-configure gd --with-freetype --with-jpeg \
    && docker-php-ext-install -j2 intl pgsql pdo_pgsql zip gd soap exif opcache \
    && rm -rf /var/lib/apt/lists/*

COPY --from=composer /usr/bin/composer /usr/local/bin/composer
WORKDIR /var/www/moodle
# Fetch an immutable official commit and check it before using the source.
RUN git init . \
    && git remote add origin https://github.com/moodle/moodle.git \
    && git fetch --depth 1 origin "${MOODLE_COMMIT}" \
    && git checkout --detach FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = "${MOODLE_COMMIT}" \
    && COMPOSER_ALLOW_SUPERUSER=1 composer install --no-dev --no-interaction --prefer-dist --optimize-autoloader \
    && composer check-platform-reqs --no-dev \
    && rm -rf .git /root/.composer /root/.cache/composer \
    && chown -R root:root /var/www/moodle \
    && chmod -R go-w /var/www/moodle

COPY config.php /var/www/moodle/config.php
COPY apache.conf /etc/apache2/sites-available/000-default.conf
COPY php.ini /usr/local/etc/php/conf.d/zz-moodle.ini
COPY entrypoint.sh /usr/local/bin/moodle-entrypoint
COPY db-state.php /usr/local/bin/moodle-db-state.php
COPY install.php /usr/local/bin/moodle-install.php
COPY health.php /usr/local/bin/moodle-health.php
RUN chmod 0755 /usr/local/bin/moodle-entrypoint \
    && chmod 0644 /var/www/moodle/config.php /usr/local/bin/moodle-*.php \
    && a2enmod rewrite headers \
    && printf 'ServerName localhost\n' > /etc/apache2/conf-available/servername.conf \
    && a2enconf servername \
    && printf '<IfModule mpm_prefork_module>\nStartServers 1\nMinSpareServers 1\nMaxSpareServers 2\nMaxRequestWorkers 4\nMaxConnectionsPerChild 500\n</IfModule>\n' > /etc/apache2/mods-available/mpm_prefork.conf

ENTRYPOINT ["/usr/local/bin/moodle-entrypoint"]
CMD ["web"]
