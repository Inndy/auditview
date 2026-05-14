import { apiFetch } from './client.js';

export function listCheckpoints(sid) {
  return apiFetch(`/api/sessions/${sid}/checkpoints`);
}

export function revertCheckpoint(sid, cid) {
  return apiFetch(`/api/sessions/${sid}/checkpoints/${cid}/revert`, {
    method: 'POST',
    body: JSON.stringify({}),
  });
}
