/**
 * Single registry of every user action in the code review view.
 *
 * Both input sources dispatch through here: `keyboard.js` resolves a KeyboardEvent
 * to an action id, `gamepad.js` resolves a polled button/axis to an action id.
 * `KeyboardHelpModal.vue` renders its table from this table, so keyboard and
 * gamepad documentation cannot drift from the bindings.
 *
 * `keys` entries are one of:
 *   'j'        plain key (e.key)
 *   ' '        space
 *   'Ctrl-d'   ctrl modifier
 *   'zz'       two-key sequence; the first char must be listed in PREFIX_KEYS
 *
 * `pad` entries are binding ids resolved against INPUTS in gamepad.js, optionally
 * prefixed with a held modifier: 'a', 'back+a', 'dpadDown', 'lstickDown'.
 */

export const PREFIX_KEYS = ['z', '[', ']']

let targets = {}

export function setTargets(t) {
  targets = t || {}
}

export function clearTargets() {
  targets = {}
}

export function isModalOpen() {
  return document.querySelector('.modal-overlay') !== null
}

export function isTextEntryFocused() {
  const el = document.activeElement
  if (!el) return false
  return el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable
}

function clickInModal(attr) {
  const overlay = [...document.querySelectorAll('.modal-overlay')].pop()
  const btn = overlay?.querySelector(`[${attr}]:not([disabled])`)
  if (!btn) return
  btn.click()
}

export const ACTIONS = {
  CURSOR_DOWN: {
    label: 'Move line cursor down',
    group: 'Motion',
    keys: ['j'],
    pad: [],
    countable: true,
    run: (t, { count = 1 }) => t.viewer?.moveCursor(count),
  },
  CURSOR_UP: {
    label: 'Move line cursor up',
    group: 'Motion',
    keys: ['k'],
    pad: [],
    countable: true,
    run: (t, { count = 1 }) => t.viewer?.moveCursor(-count),
  },
  NAV_NEXT: {
    label: 'Next item in focused pane',
    group: 'Motion',
    keys: [],
    pad: ['dpadDown', 'lstickDown'],
    run: (t) => t.view?.navFocusedPane(1),
  },
  NAV_PREV: {
    label: 'Previous item in focused pane',
    group: 'Motion',
    keys: [],
    pad: ['dpadUp', 'lstickUp'],
    run: (t) => t.view?.navFocusedPane(-1),
  },
  PAGE_DOWN: {
    label: 'Half-page down',
    group: 'Motion',
    keys: ['Ctrl-d'],
    pad: ['rt'],
    run: (t) => t.viewer?.movePage(1),
  },
  PAGE_UP: {
    label: 'Half-page up',
    group: 'Motion',
    keys: ['Ctrl-u'],
    pad: ['lt'],
    run: (t) => t.viewer?.movePage(-1),
  },
  JUMP_UNREVIEWED_NEXT: {
    label: 'Next unreviewed line',
    group: 'Motion',
    keys: [']r'],
    pad: ['rb'],
    run: (t) => t.viewer?.jumpUnreviewed(1),
  },
  JUMP_UNREVIEWED_PREV: {
    label: 'Previous unreviewed line',
    group: 'Motion',
    keys: ['[r'],
    pad: ['lb'],
    run: (t) => t.viewer?.jumpUnreviewed(-1),
  },
  JUMP_EMPTY_NEXT: {
    label: 'Next empty line (tail if none)',
    group: 'Motion',
    keys: ['}'],
    pad: ['back+rb'],
    run: (t) => t.viewer?.jumpEmpty(1),
  },
  JUMP_EMPTY_PREV: {
    label: 'Previous empty line (head if none)',
    group: 'Motion',
    keys: ['{'],
    pad: ['back+lb'],
    run: (t) => t.viewer?.jumpEmpty(-1),
  },
  VIEWPORT_TOP: {
    label: 'Cursor to top of viewport',
    group: 'Motion',
    keys: ['H'],
    pad: ['back+lt'],
    run: (t) => t.viewer?.cursorToViewportEdge('top'),
  },
  VIEWPORT_BOTTOM: {
    label: 'Cursor to bottom of viewport',
    group: 'Motion',
    keys: ['L'],
    pad: ['back+rt'],
    run: (t) => t.viewer?.cursorToViewportEdge('bottom'),
  },
  ALIGN_CENTER: {
    label: 'Center cursor in viewport',
    group: 'Motion',
    keys: ['zz'],
    pad: ['rstick'],
    run: (t) => t.viewer?.alignCursor('center'),
  },
  ALIGN_TOP: {
    label: 'Cursor line to top of viewport',
    group: 'Motion',
    keys: ['zt'],
    pad: ['back+lstick'],
    run: (t) => t.viewer?.alignCursor('start'),
  },
  ALIGN_BOTTOM: {
    label: 'Cursor line to bottom of viewport',
    group: 'Motion',
    keys: ['zb'],
    pad: ['back+rstick'],
    run: (t) => t.viewer?.alignCursor('end'),
  },
  SCROLL_PANE: {
    label: 'Scroll focused pane (cursor stays put)',
    group: 'Motion',
    keys: [],
    pad: ['rstickUp', 'rstickDown'],
    continuous: true,
    run: (t, { value = 0, dt = 16 }) => t.view?.scrollFocusedPane(value * dt),
  },

  TOGGLE_ANCHOR: {
    label: 'Set / clear selection anchor at cursor',
    group: 'Selection',
    keys: ['v', ' '],
    pad: ['lstick'],
    run: (t) => t.viewer?.toggleAnchor(),
  },
  CLEAR_SELECTION: {
    label: 'Clear cursor & selection',
    group: 'Selection',
    keys: ['Escape'],
    pad: ['b'],
    preventDefault: false,
    run: (t) => t.viewer?.clearSelection(),
  },

  ACTIVATE: {
    label: 'Activate focused pane item (mark lines / open file / jump to note)',
    group: 'Marking',
    keys: [],
    pad: ['a'],
    run: (t) => t.view?.activateFocusedPane(),
  },
  MARK_SELECTED: {
    label: 'Mark / unmark selected lines',
    group: 'Marking',
    keys: ['m'],
    pad: [],
    requiresSelection: true,
    run: (t) => t.viewer?.markSelected(),
  },
  UNMARK_SELECTED: {
    label: 'Unmark selected lines',
    group: 'Marking',
    keys: ['u'],
    pad: ['back+x'],
    requiresSelection: true,
    run: (t) => t.viewer?.unmarkSelected(),
  },
  MARK_FILE: {
    label: 'Mark / unmark entire file',
    group: 'Marking',
    keys: ['M'],
    pad: ['back+a'],
    run: (t) => t.viewer?.markWholeFile(),
  },
  UNMARK_FILE: {
    label: 'Unmark entire file',
    group: 'Marking',
    keys: ['U'],
    pad: ['back+b'],
    run: (t) => t.viewer?.unmarkWholeFile(),
  },

  ADD_NOTE: {
    label: 'Add note on selection',
    group: 'Notes',
    keys: ['n'],
    pad: ['x'],
    requiresSelection: true,
    run: (t) => t.viewer?.openNoteModal(false),
  },
  ADD_TODO: {
    label: 'Add TODO on selection',
    group: 'Notes',
    keys: ['t'],
    pad: ['y'],
    requiresSelection: true,
    run: (t) => t.viewer?.openNoteModal(true),
  },

  NEXT_FILE: {
    label: 'Next file',
    group: 'Files',
    keys: ['ArrowDown'],
    pad: ['dpadRight', 'lstickRight'],
    run: (t) => t.tree?.selectNext(),
  },
  PREV_FILE: {
    label: 'Previous file',
    group: 'Files',
    keys: ['ArrowUp'],
    pad: ['dpadLeft', 'lstickLeft'],
    run: (t) => t.tree?.selectPrev(),
  },
  LOAD_BLOCKED_FILE: {
    label: 'Load anyway (binary / oversized file)',
    group: 'Files',
    keys: ['l'],
    pad: [],
    enabled: (t) => Boolean(t.viewer?.fileBlocked),
    run: (t) => t.viewer?.loadFile(t.viewer.filePath, { force: true }),
  },

  FOCUS_PANE_NEXT: {
    label: 'Focus next pane (tree → code → notes)',
    group: 'Panes',
    keys: [],
    pad: ['back+dpadDown'],
    run: (t) => t.view?.cycleFocusedPane(1),
  },
  FOCUS_PANE_PREV: {
    label: 'Focus previous pane',
    group: 'Panes',
    keys: [],
    pad: ['back+dpadUp'],
    run: (t) => t.view?.cycleFocusedPane(-1),
  },
  TOGGLE_WRAP: {
    label: 'Toggle line wrapping',
    group: 'Panes',
    keys: [],
    pad: ['back+y'],
    run: (t) => t.view?.toggleWrap(),
  },

  SHOW_HELP: {
    label: 'Show this help',
    group: 'Other',
    keys: ['?'],
    pad: ['start'],
    run: (t) => t.view?.requestHelp(),
  },

  MODAL_CANCEL: {
    label: 'Cancel / close dialog',
    group: 'Dialogs',
    keys: ['Escape'],
    pad: ['b'],
    context: 'modal',
    preventDefault: false,
    run: () => clickInModal('data-modal-cancel'),
  },
  MODAL_CONFIRM: {
    label: 'Confirm dialog',
    group: 'Dialogs',
    keys: [],
    pad: ['start'],
    context: 'modal',
    run: () => clickInModal('data-modal-confirm'),
  },
}

export const GROUP_ORDER = ['Motion', 'Selection', 'Marking', 'Notes', 'Files', 'Panes', 'Dialogs', 'Other']

/**
 * Run an action by id. Returns true when it actually ran, so a keyboard handler
 * knows whether to call preventDefault.
 */
export function dispatch(id, params = {}) {
  const action = ACTIONS[id]
  if (!action) return false

  const wantsModal = action.context === 'modal'
  if (isModalOpen() !== wantsModal) return false
  // Review actions need the code view's refs; dialog actions work anywhere, which is
  // what lets a single global keyboard listener also close dialogs in other views.
  if (!wantsModal && !targets.view) return false

  if (action.requiresSelection && targets.viewer?.rangeMin == null) return false
  if (action.enabled && !action.enabled(targets)) return false

  action.run(targets, params)
  return true
}
