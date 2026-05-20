import { apiFetch } from './client.js'

export function listIssues(sessionId, status = null) {
  const url = `/api/sessions/${sessionId}/issues` + (status ? `?status=${status}` : '')
  return apiFetch(url)
}

export function createIssue(sessionId, title, severity = 'P2', noteIds = [], description = '') {
  return apiFetch(`/api/sessions/${sessionId}/issues`, {
    method: 'POST',
    body: JSON.stringify({ title, severity, note_ids: noteIds, description, source: 'webui' }),
  })
}

export function updateIssue(sessionId, issueId, updates) {
  const body = { ...updates }
  if (updates.status === 'resolved' || updates.status === 'dismissed') {
    body.actor = 'webui'
  }
  return apiFetch(`/api/sessions/${sessionId}/issues/${issueId}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
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
