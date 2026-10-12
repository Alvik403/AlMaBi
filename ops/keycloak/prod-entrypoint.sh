#!/bin/bash
set -eu

json_escape() {
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/[&|]/\\&/g'
}

origin="https://${ALMABI_HOST:?ALMABI_HOST is required}"
secret="$(tr -d '\r\n' < /secrets/keycloak_client_secret)"
if [ "${#secret}" -lt 32 ]; then
  echo "keycloak client secret is shorter than 32 characters" >&2
  exit 1
fi

admin_file=/opt/keycloak/data/bootstrap-admin-password
mkdir -p /opt/keycloak/data/import
if [ ! -s "$admin_file" ]; then
  tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 32 > "$admin_file" || true
fi
admin_password="$(tr -d '\r\n' < "$admin_file")"
if [ "${#admin_password}" -lt 32 ]; then
  echo "failed to prepare the Keycloak bootstrap password" >&2
  exit 1
fi

sed \
  -e "s|__PUBLIC_ORIGIN__|$(json_escape "$origin")|g" \
  -e "s|__CLIENT_SECRET__|$(json_escape "$secret")|g" \
  -e "s|__ADMIN_PASSWORD__|$(json_escape "$admin_password")|g" \
  /opt/keycloak/import-template/almabi-realm.json > /opt/keycloak/data/import/almabi-realm.json

chown -R 1000:0 /opt/keycloak/data
chmod 750 /opt/keycloak/data
chmod 640 /opt/keycloak/data/import/almabi-realm.json
chmod 600 "$admin_file"

export KC_BOOTSTRAP_ADMIN_USERNAME="${KC_BOOTSTRAP_ADMIN_USERNAME:-almabi-admin}"
export KC_BOOTSTRAP_ADMIN_PASSWORD="$admin_password"

exec runuser -u keycloak -- /opt/keycloak/bin/kc.sh start --import-realm --http-enabled=true --hostname="$origin" --hostname-strict=false --proxy-headers=xforwarded
