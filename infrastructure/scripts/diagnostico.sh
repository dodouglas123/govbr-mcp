#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/../.."
docker compose ps --all
docker compose exec -T backend python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/readyz').read().decode())"
docker compose logs --no-color --tail=30 backend
