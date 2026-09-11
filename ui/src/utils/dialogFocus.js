const FOCUSABLE = [
  'button:not([disabled])',
  'a[href]',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

const returnFocus = new WeakMap()

function focusableElements(dialog) {
  return [...dialog.querySelectorAll(FOCUSABLE)].filter(
    (element) => !element.hidden && element.getAttribute('aria-hidden') !== 'true',
  )
}

export function openDialog(component, preferredSelector = null) {
  returnFocus.set(component, document.activeElement)
  component.$nextTick(() => {
    const dialog = component.$refs.dialog
    if (!dialog) return
    const preferred = preferredSelector ? dialog.querySelector(preferredSelector) : null
    const target = preferred || focusableElements(dialog)[0] || dialog
    target.focus()
  })
}

export function restoreDialogFocus(component) {
  const target = returnFocus.get(component)
  returnFocus.delete(component)
  if (target?.isConnected && typeof target.focus === 'function') target.focus()
}

export function trapDialogFocus(component, event) {
  if (event.key !== 'Tab') return
  const dialog = component.$refs.dialog
  if (!dialog) return
  const elements = focusableElements(dialog)
  if (elements.length === 0) {
    event.preventDefault()
    dialog.focus()
    return
  }

  const first = elements[0]
  const last = elements[elements.length - 1]
  if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) {
    event.preventDefault()
    first.focus()
  }
}
