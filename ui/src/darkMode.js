import lightCss from 'highlight.js/styles/github.css?inline'
import darkCss from 'highlight.js/styles/github-dark-dimmed.css?inline'

const STORAGE_KEY = 'auditview-dark'
let hljsEl = null

function injectHljs(css) {
  if (!hljsEl) {
    hljsEl = document.createElement('style')
    hljsEl.id = 'hljs-theme'
    document.head.appendChild(hljsEl)
  }
  hljsEl.textContent = css
}

export function isDark() {
  return document.documentElement.classList.contains('dark')
}

export function setDark(dark) {
  document.documentElement.classList.toggle('dark', dark)
  localStorage.setItem(STORAGE_KEY, dark ? '1' : '0')
  injectHljs(dark ? darkCss : lightCss)
}

export function toggleDark() {
  setDark(!isDark())
}

export function initDark() {
  const stored = localStorage.getItem(STORAGE_KEY)
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
  setDark(stored !== null ? stored === '1' : prefersDark)
}
