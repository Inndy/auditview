import { apiFetch } from './client.js';
export { getConfig } from './config.js';

export function listSessions() {
  return apiFetch('/api/sessions');
}

export function createSession(data) {
  return apiFetch('/api/sessions', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}
