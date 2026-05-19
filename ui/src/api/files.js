import { apiFetch } from './client.js';

export function listFiles(sid) {
  return apiFetch(`/api/sessions/${sid}/files`);
}

export function rescanSession(sid) {
  return apiFetch(`/api/sessions/${sid}/rescan`, { method: 'POST' });
}

export async function getFile(sid, path, { force = false } = {}) {
  const qs = force ? '?force=1' : '';
  const res = await fetch(`/api/sessions/${sid}/files/${encodeURIComponent(path)}${qs}`);
  if (res.status === 422) {
    const body = await res.json().catch(() => ({}));
    const err = new Error(body.error || 'File blocked');
    err.blocked = true;
    err.reason = body.reason;
    err.size = body.size;
    throw err;
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `HTTP ${res.status}`);
  }
  return res.json();
}
