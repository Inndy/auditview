import lightCss from 'highlight.js/styles/github.css?inline'
import darkCss from 'highlight.js/styles/github-dark-dimmed.css?inline'
import { getBoolPref, setBoolPref } from './prefs.js'

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
  setBoolPref('dark', dark)
  injectHljs(dark ? darkCss : lightCss)
}

export function toggleDark() {
  setDark(!isDark())
}

export function initDark() {
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
  setDark(getBoolPref('dark', prefersDark))
}
