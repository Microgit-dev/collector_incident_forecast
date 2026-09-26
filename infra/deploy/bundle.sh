#!/usr/bin/env bash
# Комплект поставки для сервера без доступа в интернет.
#
# Запускается на машине с интернетом и Docker из корня репозитория:
#   infra/deploy/bundle.sh [каталог]            # по умолчанию dist/
# Результат:
#   collector-images-<версия>.tar.gz   все образы (свои и сторонние) для docker load
#   collector-src-<версия>.tar.gz      compose-файлы, infra/, полигон симулятора, документация
#   SHA256SUMS                          контрольные суммы
set -euo pipefail

OUT="${1:-dist}"
VERSION="$(git describe --tags --always --dirty 2>/dev/null || date +%Y%m%d)"
COMPOSE=(docker compose -f docker-compose.yml -f infra/deploy/docker-compose.customer.yml)
export KAFKA_EXTERNAL_HOST="${KAFKA_EXTERNAL_HOST:-bundle}"
[ -f .env ] || cp .env.example .env

mkdir -p "$OUT"
echo "Версия: $VERSION"

echo "1/4 Сборка своих образов"
"${COMPOSE[@]}" --profile training --profile demo --profile stand build

echo "2/4 Загрузка сторонних образов"
"${COMPOSE[@]}" --profile training --profile demo --profile stand pull --ignore-buildable --quiet

IMAGES=$("${COMPOSE[@]}" --profile training --profile demo --profile stand config --images | sort -u)
echo "$IMAGES" | sed 's/^/  /'

echo "3/4 Выгрузка образов"
# shellcheck disable=SC2086
docker save $IMAGES | gzip -1 > "$OUT/collector-images-$VERSION.tar.gz"

echo "4/4 Исходные файлы развёртывания"
git archive --format=tar.gz -o "$OUT/collector-src-$VERSION.tar.gz" HEAD

(cd "$OUT" && sha256sum "collector-images-$VERSION.tar.gz" "collector-src-$VERSION.tar.gz" > SHA256SUMS)
ls -lh "$OUT"
