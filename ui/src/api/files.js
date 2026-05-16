import { apiFetch } from './client.js';

export function listFiles(sid) {
  return apiFetch(`/api/sessions/${sid}/files`);
}

export function rescanSession(sid) {
  return apiFetch(`/api/sessions/${sid}/rescan`, { method: 'POST' });
}

export function getFile(sid, path) {
  return apiFetch(`/api/sessions/${sid}/files/${encodeURIComponent(path)}`);
}
