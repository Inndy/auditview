import { apiFetch } from './client.js';

export function getCoverage(sid) {
  return apiFetch(`/api/sessions/${sid}/coverage`);
}
