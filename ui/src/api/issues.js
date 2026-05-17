import { apiFetch } from './client.js'

export function listIssues(sessionId, status = null) {
  const url = `/api/sessions/${sessionId}/issues` + (status ? `?status=${status}` : '')
  return apiFetch(url)
}

export function createIssue(sessionId, title, severity = 'P2', noteIds = [], description = '') {
  return apiFetch(`/api/sessions/${sessionId}/issues`, {
    method: 'POST',
    body: JSON.stringify({ title, severity, note_ids: noteIds, description }),
  })
}

export function updateIssue(sessionId, issueId, updates) {
  return apiFetch(`/api/sessions/${sessionId}/issues/${issueId}`, {
    method: 'PATCH',
    body: JSON.stringify(updates),
  })
}

export function deleteIssue(sessionId, issueId) {
  return apiFetch(`/api/sessions/${sessionId}/issues/${issueId}`, { method: 'DELETE' })
}

export function getIssueNotes(sessionId, issueId) {
  return apiFetch(`/api/sessions/${sessionId}/issues/${issueId}/notes`)
}

export function attachNoteToIssue(sessionId, noteId, issueId) {
  return apiFetch(`/api/sessions/${sessionId}/notes/${noteId}/issue`, {
    method: 'PUT',
    body: JSON.stringify({ issue_id: issueId }),
  })
}
