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

function onKeyDown(e) {
  // While a dialog is up, only dialog actions run — and unlike the rest, they are
  // allowed to fire with a text field focused (that is where the caret usually is).
  if (isModalOpen()) {
    for (const id of PLAIN[keyOf(e)] || []) {
      if (ACTIONS[id].context === 'modal' && tryDispatch(e, id)) return
    }
    return
  }

  // Preserve native keyboard behavior for every interactive element. In
  // particular, Space must activate a focused button instead of toggling the
  // code selection anchor, and arrows in a select must not change files.
  if (e.target?.closest?.(
    'button, a, input, textarea, select, [contenteditable], [role="button"], [role="link"]',
  )) return

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
