import { apiFetch } from './client.js'

export function getConfig() {
  return apiFetch('/api/config')
}

export function setMcpSession(sessionId) {
  return apiFetch('/api/config/mcp-session', {
    method: 'PUT',
    body: JSON.stringify({ session_id: sessionId }),
  })
}

export function clearMcpSession() {
  return apiFetch('/api/config/mcp-session', { method: 'DELETE' })
}

export function resolvePath(path) {
  return apiFetch('/api/config/resolve-path', {
    method: 'POST',
    body: JSON.stringify({ path }),
  })
}
