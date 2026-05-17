---
description: Review the SSE channel end-to-end — backend fan-out with silent drop on full, UI singleton subscribe/unsubscribe and reconnection, router-driven session switching. Use when touching watcher.py broadcast, events.py, ui/src/api/events.js, or any component that calls sseClient.on().
allowed-tools: Read, Glob, Grep
---

# Lens: SSE lifecycle

**Why this matters for this codebase:** SSE is the only push channel. The backend fans events out via per-client `asyncio.Queue` with `put_nowait` and **silently drops** on overflow. The UI has a singleton `sseClient` whose `status` is a reactive `ref()`; components subscribe via `.on()` and receive an unsubscribe function — which they reportedly don't call on unmount. The router watches the current session and re-targets `sseClient` on route changes. Each piece is plausible alone; together they enable lost events, listener accumulation across remounts, and a "permanently disconnected" UI that the user can't see.

## Start at

- **Backend**:
  - `auditview/core/watcher.py` → `broadcast()` (~line 94–101): `put_nowait`, queue size 128, swallow `QueueFull`.
  - `auditview/api/events.py` → `event_stream()` route: per-client `asyncio.Queue` register/unregister, 15 s heartbeat, generator `finally:` for cleanup on disconnect.
  - Shutdown signaling in `auditview/app.py` (the on-shutdown handler sends `{type:"shutdown"}` to all clients).
- **UI**:
  - `ui/src/api/events.js` → `sseClient` singleton: `setSessionId`, `_open`, `_scheduleRetry`, `on(event, cb)`, `status = ref('disconnected')`.
  - `ui/src/router/index.js` — the watcher on a computed `sseSessionId` that calls `sseClient.setSessionId()`.
  - Every component that calls `sseClient.on(...)` — start with `CodeViewer.vue`, then grep for `sseClient.on(` across `ui/src/`.
  - `SSEStatusIndicator.vue` — what status values it surfaces and how.

## Follow

A `file_changed` event from the moment the file is saved:

1. Watchdog → loop → reconcile → `broadcast({type: "file_changed", rel_path})`.
2. For each registered client queue → `put_nowait` (may drop).
3. `event_stream` consumer reads from queue → serializes to SSE frame → `yield`.
4. EventSource `onmessage` → `_dispatch` → every registered `on('file_changed')` callback.
5. Component handler reloads file content.

Then a session switch:

1. Route changes → router watcher observes new `sseSessionId` → calls `sseClient.setSessionId(new_id)` → `close()` old EventSource → `_open(new_id)`.
2. Component that was subscribed: does it stay subscribed? Does its handler still fire for the *new* session?

## Look for

- **Silent drop on backend queue full**: 128 is chosen but not enforced anywhere visible to the client. Compute realistic burst (e.g. mass file move, `git checkout` of a branch) and ask whether 128 will hold. If a `shutdown` event is broadcast to a full queue, the client never learns the server is going down — confirm shutdown events are *not* `put_nowait`-with-drop.
- **`event_stream` generator cleanup**: confirm the `finally:` block always unregisters the client queue. If a client drops mid-stream and unregister doesn't run, the queue accumulates forever; on next broadcast, `put_nowait` fills it and drops *real* clients' events too (no — each client has its own queue, so it leaks memory but not events; still a leak).
- **Heartbeat timing & idle proxies**: 15 s heartbeat. Some reverse proxies (nginx) drop idle SSE at 60 s — confirm the heartbeat is `<` any proxy idle timeout in the deployment guide, or just document the server is dev-only.
- **UI: listener leak on remount**: every `sseClient.on('file_changed', handler)` returns an unsubscribe function. Grep for callers and confirm they capture it and invoke it in `beforeUnmount`. If a component remounts (route navigation back) without unsubscribing, handlers accumulate and fire N times per event. CodeViewer is the prime suspect per the survey.
- **Duplicate registration on session switch**: when `setSessionId` reopens, the listeners dict persists (it's on the singleton). Confirm there's no path where `_open` re-registers internal listeners on top of existing ones.
- **Reconnect storm vs `shutdown`**: `status === 'shutdown'` bypasses retry. If the dev script restarts the server, the UI was told `shutdown` and now never reconnects. Verify either: (a) the user gets a visible "reload" prompt, or (b) the reconnect actually fires after a backoff and ignores the prior shutdown after some grace period.
- **Backoff cap**: 1 s → 30 s exponential. With many idle tabs, the thundering-herd on server restart is bounded by jitter — confirm jitter exists, not just deterministic delay.
- **`status` consumer surface**: `SSEStatusIndicator` reads `status.value`. Confirm every state has a visible representation; "connecting" lingering for 5+ seconds with no indicator means the user thinks the page is live when it isn't.
- **Race on rapid session switch**: user clicks session A, then immediately session B. `setSessionId(A)` opens → router watcher fires for B → `close()` + `_open(B)`. If A's `_open` callback resolves after B's, the A EventSource may still fire one event for A's session. Trace whether the singleton guards against this with an epoch/id token.
- **No SSE in nvim** — by design, but contrast: a backend-side mark from the web UI never reaches an open nvim buffer. See [[codeview-lens-nvim-cache-drift]] — the implication is that "live" is asymmetric, and any review of "real-time" features should call out this gap.
- **Coupling shape — router owning SSE**: `router/index.js` watches session and drives `sseClient`. This is implicit coupling — a future contributor adding a non-session-bound view that needs SSE has no obvious hook. Note as a design smell, not a bug.

## Diagnostic heuristic

For every `sseClient.on(` call site, the same file must contain the corresponding unsubscribe in a lifecycle hook. Missing pair = finding.

## Universal review principles

Apply these across every lens, in addition to the lens-specific items above:

- A defensive guard (`if err`, boundary check, type-assertion guard) is a question, not an answer: *is this patching a symptom, or is the data model wrong?*
- Find the **root shape of a bug class**, not individual instances.
- Code that forces the reader to hold context across distant locations is a design smell, not just a readability issue.
- Absence of a structure is a finding: concurrency without a documented ownership model, an API without a documented error shape, a cache without a documented invalidation rule.
- If a name needs a comment to clarify its meaning, the name is wrong. Identifiers that leak implementation detail, lie about scope, or force a reader to look elsewhere are bugs.
- Distinguish *validating* illegal state from *preventing* it. A guard against an "impossible" state is a sign the type or data model should make the state unrepresentable.
- A function that can't be described without "and" is doing more than one thing — composition candidate, not refactor target.
- Question every abstraction that adds indirection without reducing complexity. More code is more surface, not more safety; flag wrappers harder to reason about than what they wrap.

## Related lenses

- Backend dropping events under load: see queue & lock discussion in [[codeview-lens-concurrency]].
- What user-visible signal exists when SSE silently dies: [[codeview-lens-error-propagation]].
