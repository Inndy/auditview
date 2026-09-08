import { apiFetch } from './client.js';

// `line` is 1-based, matching every other line number in the API. `character`
// is a 0-based UTF-16 code-unit offset -- which is what a DOM text-node offset
// already is, so it is passed through untouched.
export function getDefinition(sid, { filePath, line, character }) {
  return apiFetch(`/api/sessions/${sid}/lsp/definition`, {
    method: 'POST',
    body: JSON.stringify({ file_path: filePath, line, character }),
  });
}

export function getLspStatus(sid) {
  return apiFetch(`/api/sessions/${sid}/lsp/status`);
}

// Only paths a definition query actually returned are previewable; anything
// else is refused with 403 by design.
export function getPreview(sid, path, line) {
  const qs = `?path=${encodeURIComponent(path)}&line=${line}`;
  return apiFetch(`/api/sessions/${sid}/lsp/preview${qs}`);
}
