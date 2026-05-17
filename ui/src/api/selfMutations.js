// Short-lived registry of mutations this client just issued, so the matching
// SSE event that comes back doesn't get treated as a remote change. Consume-on-
// read: once a subscriber checks for an id, it is cleared.

const WINDOW_MS = 3000;
const recent = new Map(); // key "kind:id" -> timestamp

function prune(now) {
  for (const [k, t] of recent) {
    if (now - t > WINDOW_MS) recent.delete(k);
  }
}

export function recordSelfMutation(kind, id) {
  if (id == null) return;
  recent.set(`${kind}:${id}`, Date.now());
  prune(Date.now());
}

export function consumeSelfMutation(kind, id) {
  if (id == null) return false;
  const key = `${kind}:${id}`;
  const t = recent.get(key);
  if (t === undefined) return false;
  recent.delete(key);
  return Date.now() - t <= WINDOW_MS;
}
