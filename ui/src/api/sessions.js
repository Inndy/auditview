import { apiFetch } from './client.js';

export function listSessions() {
  return apiFetch('/api/sessions');
}

export function createSession(data) {
  return apiFetch('/api/sessions', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export function updateSession(sid, data) {
  return apiFetch(`/api/sessions/${sid}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export function purgePath(sid, path) {
  return apiFetch(`/api/sessions/${sid}/purge`, {
    method: 'POST',
    body: JSON.stringify({ path }),
  });
}
