#!/bin/sh
# Сервис cliproxy-init (раздел 20.3 ТЗ): раскладывает конфигурацию
# CLIProxyAPI с ключами из .env в volume прокси. Идемпотентен — запускается
# при каждом старте стека и заново рендерит шаблон.
set -eu

TEMPLATE=/opt/cliproxy/config.template.yaml
DATA_DIR=/data

for name in CLIPROXY_API_KEY CLIPROXY_MANAGEMENT_KEY; do
  eval "value=\${$name:-}"
  if [ -z "$value" ]; then
    echo "cliproxy-init: не задана переменная $name в .env" >&2
    exit 1
  fi
  # Ключи генерирует install.sh (`openssl rand -hex`): только [0-9a-f].
  case "$value" in
    *[!0-9A-Za-z]*)
      echo "cliproxy-init: $name должен состоять из букв и цифр" >&2
      exit 1
      ;;
  esac
done

mkdir -p "$DATA_DIR/auths"
chmod 700 "$DATA_DIR/auths"
umask 077
sed \
  -e "s/__CLIPROXY_API_KEY__/$CLIPROXY_API_KEY/" \
  -e "s/__CLIPROXY_MANAGEMENT_KEY__/$CLIPROXY_MANAGEMENT_KEY/" \
  "$TEMPLATE" > "$DATA_DIR/config.yaml.tmp"
mv "$DATA_DIR/config.yaml.tmp" "$DATA_DIR/config.yaml"
echo "cliproxy-init: конфигурация записана"
