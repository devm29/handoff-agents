#!/usr/bin/env bash
# Starts the API, one worker and the web app together; Ctrl-C stops all three.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HANDOFF="$ROOT/backend/.venv/bin/handoff"

trap 'kill 0' EXIT INT TERM

(cd "$ROOT/backend" && "$HANDOFF" api) &
(cd "$ROOT/backend" && "$HANDOFF" worker) &
(cd "$ROOT/frontend" && pnpm dev) &
wait
