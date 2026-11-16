#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/../.."
umask 077
mkdir -p backups
dest="backups/govbr-$(date -u +%Y%m%dT%H%M%SZ).dump"
temp="$dest.tmp"
trap 'rm -f "$temp"' EXIT HUP INT TERM
docker compose exec -T postgres pg_dump -Fc -U govbr -d govbr > "$temp"
docker compose exec -T postgres pg_restore --list < "$temp" > /dev/null
mv "$temp" "$dest"
printf '%s\n' "$dest"
