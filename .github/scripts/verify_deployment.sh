#!/usr/bin/env bash
# Проверка после развёртывания (раздел 20.7 ТЗ): `GET /api/health` отвечает 200
# с SHA развёрнутого коммита и фронтенд отдаёт index.html. Ждёт до
# HEALTH_TIMEOUT_SECONDS, опрашивая раз в HEALTH_POLL_SECONDS.
#
#   DEPLOY_DOMAIN=tracker.example.com .github/scripts/verify_deployment.sh <sha>

set -euo pipefail

EXPECTED_SHA="${1:?нужен SHA развёрнутого коммита}"
BASE_URL="https://${DEPLOY_DOMAIN:?не задан DEPLOY_DOMAIN}"
TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-300}"
POLL_SECONDS="${HEALTH_POLL_SECONDS:-10}"
REQUEST_TIMEOUT_SECONDS=10
# Корневой элемент SPA (frontend/index.html).
INDEX_MARKER='<div id="root">'

deployed_version() {
  curl -fsS --max-time "${REQUEST_TIMEOUT_SECONDS}" "${BASE_URL}/api/health" \
    | python3 -c 'import json, sys; print(json.load(sys.stdin).get("version", ""))'
}

frontend_served() {
  curl -fsS --max-time "${REQUEST_TIMEOUT_SECONDS}" "${BASE_URL}/" | grep -qF "${INDEX_MARKER}"
}

deadline=$(( $(date +%s) + TIMEOUT_SECONDS ))
while true; do
  version="$(deployed_version 2>/dev/null || true)"
  if [ "${version}" = "${EXPECTED_SHA}" ] && frontend_served; then
    echo "Развёрнут ${EXPECTED_SHA}: /api/health и index.html отвечают"
    exit 0
  fi
  if [ "$(date +%s)" -ge "${deadline}" ]; then
    echo "::error::За ${TIMEOUT_SECONDS} с не дождались ${EXPECTED_SHA}: /api/health сообщает «${version:-нет ответа}»"
    exit 1
  fi
  sleep "${POLL_SECONDS}"
done
