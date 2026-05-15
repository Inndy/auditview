import { apiFetch } from './client.js';

export function getNotes(sid) {
  return apiFetch(`/api/sessions/${sid}/notes`);
}

export function listNotes(sid) {
  return apiFetch(`/api/sessions/${sid}/notes`);
}

export function createNote(sid, data) {
  return apiFetch(`/api/sessions/${sid}/notes`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export function updateNote(sid, nid, data) {
  return apiFetch(`/api/sessions/${sid}/notes/${nid}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export function deleteNote(sid, nid) {
  return apiFetch(`/api/sessions/${sid}/notes/${nid}`, {
    method: 'DELETE',
  });
}
