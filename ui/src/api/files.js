import { apiFetch } from './client.js';

export function listFiles(sid) {
  return apiFetch(`/api/sessions/${sid}/files`);
}

export function rescanSession(sid) {
  return apiFetch(`/api/sessions/${sid}/rescan`, { method: 'POST' });
}

export function getFile(sid, path, skipComments = true) {
  const sc = skipComments ? '1' : '0';
  return apiFetch(`/api/sessions/${sid}/files/${encodeURIComponent(path)}?skip_comments=${sc}`);
}
