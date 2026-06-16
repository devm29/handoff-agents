#!/usr/bin/env bash
# Runs a throwaway PostgreSQL on port 5504 with data under .data/postgres (no Docker needed).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="$ROOT/.data/postgres"
PORT="${PGPORT:-5504}"

usable() {
  [ -n "${1:-}" ] && [ -x "$1/postgres" ] && [ -x "$1/pg_ctl" ] && [ -x "$1/initdb" ] && "$1/postgres" --version >/dev/null 2>&1
}

find_bin() {
  local candidates=()
  [ -n "${PG_BIN:-}" ] && candidates+=("$PG_BIN")
  if command -v brew >/dev/null 2>&1; then
    for version in 17 16 18; do
      candidates+=("$(brew --prefix "postgresql@$version" 2>/dev/null)/bin")
    done
  fi
  command -v pg_config >/dev/null 2>&1 && candidates+=("$(pg_config --bindir)")
  command -v pg_ctl >/dev/null 2>&1 && candidates+=("$(dirname "$(command -v pg_ctl)")")
  for dir in "${candidates[@]}"; do
    if usable "$dir"; then
      echo "$dir"
      return 0
    fi
  done
  return 1
}

if ! BIN="$(find_bin)"; then
  echo "No working PostgreSQL server binaries found. Install postgresql@17 or set PG_BIN to its bin directory." >&2
  exit 69
fi

if [ -f "$DATA/PG_VERSION" ]; then
  data_major="$(cat "$DATA/PG_VERSION")"
  bin_major="$("$BIN/postgres" --version | sed -E 's/[^0-9]*([0-9]+).*/\1/')"
  if [ "$data_major" != "$bin_major" ]; then
    echo "$DATA was created by PostgreSQL $data_major but $BIN is $bin_major. Set PG_BIN or remove .data/postgres." >&2
    exit 69
  fi
fi

case "${1:-start}" in
  start)
    mkdir -p "$ROOT/.data"
    if [ ! -f "$DATA/PG_VERSION" ]; then
      "$BIN/initdb" -D "$DATA" -U handoff --auth=trust -E UTF8 >/dev/null
    fi
    if ! "$BIN/pg_ctl" -D "$DATA" status >/dev/null 2>&1; then
      "$BIN/pg_ctl" -D "$DATA" -o "-p $PORT -k /tmp -c listen_addresses=127.0.0.1" -l "$ROOT/.data/postgres.log" -w start >/dev/null
    fi
    for db in handoff handoff_test; do
      "$BIN/psql" -h 127.0.0.1 -p "$PORT" -U handoff -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$db'" | grep -q 1 \
        || "$BIN/createdb" -h 127.0.0.1 -p "$PORT" -U handoff "$db"
    done
    echo "PostgreSQL ready on 127.0.0.1:$PORT ($BIN)"
    ;;
  stop)
    "$BIN/pg_ctl" -D "$DATA" stop >/dev/null && echo "PostgreSQL stopped"
    ;;
  status)
    "$BIN/pg_ctl" -D "$DATA" status
    ;;
  *)
    echo "usage: $0 [start|stop|status]" >&2
    exit 64
    ;;
esac
