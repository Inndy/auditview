#!/bin/bash
# Stop backend + frontend dev servers.
# Removes restart flags first so supervisors exit instead of relaunching.

set -u

DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PID="$DIR/.dev-backend.pid"
FRONTEND_PID="$DIR/.dev-frontend.pid"
BACKEND_RESTART="$DIR/.dev-backend.restart"
FRONTEND_RESTART="$DIR/.dev-frontend.restart"

rm -f "$BACKEND_RESTART" "$FRONTEND_RESTART"

stop() {
    local pidfile=$1 name=$2 pid
    [ -f "$pidfile" ] || return 0
    pid=$(cat "$pidfile" 2>/dev/null)
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null || return 0
    echo "Stopping $name (PID $pid)..."
    kill "$pid" 2>/dev/null || true
}

stop "$BACKEND_PID"  backend
stop "$FRONTEND_PID" frontend

rm -f "$BACKEND_PID" "$FRONTEND_PID"
echo "✓ stopped"
