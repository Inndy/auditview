const EXT_LANG = {
  py: 'python', js: 'javascript', ts: 'typescript', jsx: 'javascript',
  tsx: 'typescript', vue: 'xml', html: 'html', css: 'css', scss: 'scss',
  json: 'json', md: 'markdown', sh: 'bash', bash: 'bash', go: 'go',
  rs: 'rust', c: 'c', cpp: 'cpp', h: 'c', java: 'java', rb: 'ruby',
  yaml: 'yaml', yml: 'yaml', toml: 'ini', sql: 'sql', xml: 'xml',
}

export function escapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

export function highlightSource(hljs, path, src) {
  if (!hljs) return escapeHtml(src)
  const ext = String(path).split('.').pop().toLowerCase()
  const lang = EXT_LANG[ext]
  try {
    if (lang && hljs.getLanguage(lang)) {
      return hljs.highlight(src, { language: lang }).value
    }
    return hljs.highlightAuto(src).value
  } catch {
    return escapeHtml(src)
  }
}
