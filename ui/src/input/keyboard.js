import { ACTIONS, PREFIX_KEYS, dispatch, isModalOpen } from './actions.js'

const PENDING_TIMEOUT_MS = 1000

const SEQ = {}
const PLAIN = {}

for (const [id, action] of Object.entries(ACTIONS)) {
  for (const spec of action.keys) {
    if (spec.length === 2 && PREFIX_KEYS.includes(spec[0])) {
      SEQ[spec] = id
    } else {
      ;(PLAIN[spec] ||= []).push(id)
    }
  }
}

let pendingOp = null
let pendingTimer = null
let countBuffer = ''
let handler = null

function resetPending() {
  pendingOp = null
  if (pendingTimer !== null) {
    clearTimeout(pendingTimer)
    pendingTimer = null
  }
  countBuffer = ''
}

function setPendingOp(op) {
  pendingOp = op
  if (pendingTimer !== null) clearTimeout(pendingTimer)
  pendingTimer = setTimeout(() => {
    pendingOp = null
    pendingTimer = null
  }, PENDING_TIMEOUT_MS)
}

function consumeCount() {
  const n = countBuffer ? parseInt(countBuffer, 10) : 1
  countBuffer = ''
  return Math.min(Math.max(n, 1), 9999)
}

function keyOf(e) {
  return e.ctrlKey ? `Ctrl-${e.key}` : e.key
}

function tryDispatch(e, id, params) {
  if (!dispatch(id, params)) return false
  if (ACTIONS[id].preventDefault !== false) e.preventDefault()
  return true
}

const INTERACTIVE_SELECTOR =
  'button, a, input, textarea, select, [contenteditable], [role="button"], [role="link"]'

// Input types whose native keyboard behavior is limited to activation: they hold
// no caret and consume no motion key.
const ACTIVATION_ONLY_INPUT_TYPES = new Set([
  'checkbox',
  'radio',
  'button',
  'submit',
  'reset',
  'image',
])

const ACTIVATION_KEYS = new Set([' ', 'Enter'])
const ARROW_KEYS = new Set(['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'])

/**
 * Whether the focused element genuinely needs this key, in which case the review
 * bindings must stand aside. Only Space/Enter (and arrows inside a radio group)
 * are native on a checkbox, a button or a link, so yielding *every* key to them
 * left j/k dead after a single click on a file row or a filter checkbox — focus
 * stays on the control long after the click that put it there. Anything holding a
 * caret or its own typeahead — text field, textarea, contenteditable, select —
 * still owns the whole keyboard.
 */
export function ownsKeyNatively(e) {
  const el = e.target?.closest?.(INTERACTIVE_SELECTOR)
  if (!el) return false

  const tag = el.tagName
  if (tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable) return true
  if (tag === 'INPUT') {
    const type = (el.type || 'text').toLowerCase()
    if (!ACTIVATION_ONLY_INPUT_TYPES.has(type)) return true
    if (type === 'radio' && ARROW_KEYS.has(e.key)) return true
  }

  if (e.ctrlKey || e.metaKey || e.altKey) return false
  return ACTIVATION_KEYS.has(e.key)
}

function onKeyDown(e) {
  // While a dialog is up, only dialog actions run — and unlike the rest, they are
  // allowed to fire with a text field focused (that is where the caret usually is).
  if (isModalOpen()) {
    for (const id of PLAIN[keyOf(e)] || []) {
      if (ACTIONS[id].context === 'modal' && tryDispatch(e, id)) return
    }
    return
  }

  if (ownsKeyNatively(e)) return

  const key = e.key

  if (pendingOp) {
    const id = SEQ[pendingOp + key]
    resetPending()
    if (id && tryDispatch(e, id)) return
  }

  if (/^[0-9]$/.test(key) && !e.ctrlKey && !e.metaKey && !e.altKey) {
    e.preventDefault()
    if (countBuffer === '' && key === '0') return
    countBuffer += key
    return
  }

  const ids = PLAIN[keyOf(e)] || []
  const countable = ids.find((id) => ACTIONS[id].countable)
  if (countable) {
    if (tryDispatch(e, countable, { count: consumeCount() })) return
  }

  countBuffer = ''

  if (PREFIX_KEYS.includes(key)) {
    e.preventDefault()
    setPendingOp(key)
    return
  }

  for (const id of ids) {
    if (tryDispatch(e, id)) return
  }
}

export function attachKeyboard() {
  if (handler) return
  handler = onKeyDown
  document.addEventListener('keydown', handler)
}

export function detachKeyboard() {
  if (!handler) return
  document.removeEventListener('keydown', handler)
  handler = null
  resetPending()
}
