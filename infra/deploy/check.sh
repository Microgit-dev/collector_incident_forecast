#!/usr/bin/env bash
# Проверка после развёртывания или обновления. Запуск на сервере из каталога системы:
#   infra/deploy/check.sh https://forecast.corp.local
# Ничего не меняет: только читает состояние контейнеров, настройки и заголовки. Состав compose-файлов
# берётся из COMPOSE_FILE в .env.
set -uo pipefail

URL="${1:-https://localhost}"
fail=0
ok() { printf '  [ ok ] %s\n' "$1"; }
bad() { printf '  [FAIL] %s\n' "$1"; fail=1; }

echo "Контейнеры"
while read -r name state code health; do
  case "$state/$code/$health" in
    running/*/healthy | running/*/) ok "$name" ;;
    running/*/starting) warn "$name ещё запускается — повторите проверку через минуту" ;;
    exited/0/*) ok "$name (одноразовый, завершён)" ;;
    *) bad "$name: $state, код $code ${health:-}" ;;
  esac
done < <(docker compose ps -a --format '{{.Service}} {{.State}} {{.ExitCode}} {{.Health}}')

echo "Миграции и инициализация"
code=$(docker compose ps -a --format '{{.Service}} {{.ExitCode}}' | awk '$1=="migrate"{print $2}')
[ "$code" = "0" ] && ok "migrate завершился успешно" || bad "migrate: код $code — docker compose logs migrate"

echo "Настройки безопасности Django"
if out=$(docker compose exec -T backend python manage.py check --deploy --fail-level ERROR 2>&1); then
  ok "manage.py check --deploy"
else
  bad "manage.py check --deploy"; echo "$out" | sed 's/^/        /'
fi
docker compose exec -T backend python manage.py check --deploy 2>&1 | grep -E "collector\.S00" | sed 's/^/  [warn] /'

echo "Доступность"
for path in / /health/ /api/v1/auth/me/; do
  code=$(curl -sk -o /dev/null -w '%{http_code}' "$URL$path")
  case "$path:$code" in
    /:200 | /health/:200 | /api/v1/auth/me/:401) ok "$path → $code" ;;
    *) bad "$path → $code" ;;
  esac
done

echo "Заголовки"
headers=$(curl -skI "$URL/")
for h in Strict-Transport-Security Content-Security-Policy X-Frame-Options X-Content-Type-Options; do
  grep -qi "^$h:" <<<"$headers" && ok "$h" || bad "нет $h"
done
grep -qi '^Server:' <<<"$headers" && bad "заголовок Server не скрыт" || ok "Server скрыт"

echo "Сертификат"
host=$(sed -E 's#https?://([^/:]+).*#\1#' <<<"$URL")
port=$(sed -nE 's#https?://[^/:]+:([0-9]+).*#\1#p' <<<"$URL"); port=${port:-443}
if command -v openssl >/dev/null; then
  echo | openssl s_client -connect "$host:$port" -servername "$host" 2>/dev/null \
    | openssl x509 -noout -subject -issuer -enddate 2>/dev/null | sed 's/^/  /'
fi

echo
[ $fail -eq 0 ] && echo "Итог: всё в порядке" || echo "Итог: есть ошибки, см. [FAIL]"
exit $fail
