#!/bin/bash
# Fresh start of backend + frontend dev servers in tmux.
# Run once after reboot / dev-stop.sh. Use dev-restart.sh to restart later.
#
# Usage: ./dev-start.sh [audit-path]

set -u

DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$DIR")"
BACKEND_PID="$DIR/.dev-backend.pid"
FRONTEND_PID="$DIR/.dev-frontend.pid"
BACKEND_RESTART="$DIR/.dev-backend.restart"
FRONTEND_RESTART="$DIR/.dev-frontend.restart"

alive()  { [ -f "$1" ] && kill -0 "$(cat "$1" 2>/dev/null)" 2>/dev/null; }
pid_of() { cat "$1" 2>/dev/null; }

# ── Frontend pane mode (entered via tmux split below) ─────────────────────────
if [ "${AUDITVIEW_DEV_FRONTEND:-}" = 1 ]; then
    cd "$ROOT/ui"
    child=
    trap '[ -n "$child" ] && pkill -P "$child" 2>/dev/null && kill "$child" 2>/dev/null; rm -f "$FRONTEND_PID" "$FRONTEND_RESTART"' EXIT
    while :; do
        rm -f "$FRONTEND_RESTART"
        pnpm run dev --host & child=$!
        echo "$child" > "$FRONTEND_PID"
        wait "$child"
        [ -f "$FRONTEND_RESTART" ] || break
        echo "── frontend restart ──"
    done
    exit
fi

# Refuse if anything is already running — restart is dev-restart.sh's job.
if alive "$BACKEND_PID" || alive "$FRONTEND_PID"; then
    echo "Error: dev servers already running. Use ./scripts/dev-restart.sh." >&2
    exit 1
fi

[ -n "${TMUX:-}" ] || { echo "Error: must run inside tmux." >&2; exit 1; }

AUDIT_PATH="${1:-$ROOT}"
rm -f "$BACKEND_PID" "$FRONTEND_PID" "$BACKEND_RESTART" "$FRONTEND_RESTART"

tmux split-window -v -c "$ROOT/ui" \
    "AUDITVIEW_DEV_FRONTEND=1 $(printf '%q' "$DIR/dev-start.sh")" \
    || { echo "Error: tmux split-window failed." >&2; exit 1; }

cd "$ROOT"
child=
trap '
    [ -n "$child" ] && kill "$child" 2>/dev/null
    alive "$FRONTEND_PID" && pkill -P "$(pid_of "$FRONTEND_PID")" 2>/dev/null && kill "$(pid_of "$FRONTEND_PID")" 2>/dev/null
    rm -f "$BACKEND_PID" "$BACKEND_RESTART"
    true
' EXIT

while :; do
    rm -f "$BACKEND_RESTART"
    uv run auditview --debug "$AUDIT_PATH" & child=$!
    echo "$child" > "$BACKEND_PID"
    wait "$child"
    [ -f "$BACKEND_RESTART" ] || break
    echo "── backend restart ──"
done
