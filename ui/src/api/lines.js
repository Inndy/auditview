import { apiFetch } from './client.js';

export function markLines(sid, data) {
  return apiFetch(`/api/sessions/${sid}/lines/mark`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}
