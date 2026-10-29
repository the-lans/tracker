#!/usr/bin/env bash
# Smoke-тест продового образа фронтенда (frontend/Dockerfile): образ
# собирается (ловит поломки при смене версии Node), SPA-маршруты отдают
# index.html, а отсутствующий бандл — 404, а не index.html под видом JS;
# index.html не кешируется, хешированные бандлы — кешируются навсегда.
set -euo pipefail

IMAGE="tracker-frontend:smoke"
PORT="${SMOKE_PORT:-18080}"
BASE_URL="http://localhost:${PORT}"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

docker build -q -t "$IMAGE" "$ROOT_DIR/frontend" >/dev/null
container_id="$(docker run -d -p "${PORT}:80" "$IMAGE")"
trap 'docker rm -f "$container_id" >/dev/null' EXIT

for _ in $(seq 1 20); do
  curl -sf -o /dev/null "$BASE_URL/" && break
  sleep 0.5
done

failures=0
expect() {
  local path="$1" expected_code="$2" expected_type="$3"
  local actual
  actual="$(curl -s -o /dev/null -w '%{http_code} %{content_type}' "$BASE_URL$path")"
  if [[ "$actual" == "$expected_code $expected_type"* ]]; then
    echo "ok   $path -> $actual"
  else
    echo "FAIL $path -> $actual (ожидалось $expected_code $expected_type)"
    failures=$((failures + 1))
  fi
}

expect_cache() {
  local path="$1" expected="$2"
  local actual
  actual="$(curl -s -o /dev/null -D - "$BASE_URL$path" | tr -d '\r' | { grep -i '^cache-control:' || true; } | cut -d' ' -f2-)"
  if [[ "$actual" == "$expected" ]]; then
    echo "ok   $path Cache-Control: $actual"
  else
    echo "FAIL $path Cache-Control: '$actual' (ожидалось '$expected')"
    failures=$((failures + 1))
  fi
}

expect "/" 200 "text/html"
expect "/tasks/00000000-0000-0000-0000-000000000000" 200 "text/html"
expect "/admin" 200 "text/html"
expect "/assets/missing-bundle.js" 404 ""

bundle_path="$(curl -s "$BASE_URL/" | grep -o '/assets/[^"]*\.js' | head -1)"
if [[ -z "$bundle_path" ]]; then
  echo "FAIL index.html не ссылается на JS-бандл из /assets/"
  failures=$((failures + 1))
else
  expect "$bundle_path" 200 "application/javascript"
  expect_cache "$bundle_path" "public, max-age=31536000, immutable"
fi
expect_cache "/" "no-cache"
expect_cache "/tasks/00000000-0000-0000-0000-000000000000" "no-cache"

exit "$failures"
