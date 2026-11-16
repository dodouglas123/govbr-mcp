#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/../.."
if [ ! -f .env ]; then
  umask 077
  secret="$(openssl rand -hex 24)"
  sed "s/^GOVBR_DB_PASSWORD=$/GOVBR_DB_PASSWORD=$secret/" .env.example > .env
fi
docker compose config --quiet
docker compose up -d --build --wait --remove-orphans
