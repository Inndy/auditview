#!/bin/bash
# Restart running dev servers in place by signaling their supervisors.
# Errors if servers are not currently running — start with dev-start.sh first.

set -u

DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PID="$DIR/.dev-backend.pid"
FRONTEND_PID="$DIR/.dev-frontend.pid"
BACKEND_RESTART="$DIR/.dev-backend.restart"
FRONTEND_RESTART="$DIR/.dev-frontend.restart"

alive() { [ -f "$1" ] && kill -0 "$(cat "$1" 2>/dev/null)" 2>/dev/null; }

if ! alive "$BACKEND_PID" || ! alive "$FRONTEND_PID"; then
    echo "Error: dev servers not running. Ask user to run ./scripts/dev-start.sh first." >&2
    exit 1
fi

touch "$BACKEND_RESTART" "$FRONTEND_RESTART"
pkill -P "$(cat "$BACKEND_PID")" "$(cat "$FRONTEND_PID")" 2>/dev/null || true
kill "$(cat "$BACKEND_PID")" "$(cat "$FRONTEND_PID")" 2>/dev/null || true
echo "✓ restart triggered"
