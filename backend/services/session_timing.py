"""Общие интервалы жизни сессии и её маршрута в Redis."""

HEARTBEAT_INTERVAL_SECONDS = 30.0
# Три пропущенных обновления подряд — воркера больше нет.
HEARTBEAT_TTL_SECONDS = 90
