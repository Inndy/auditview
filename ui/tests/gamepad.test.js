import assert from 'node:assert/strict'
import test from 'node:test'

const prefs = new Map()
globalThis.localStorage = {
  getItem(key) {
    return prefs.has(key) ? prefs.get(key) : null
  },
  setItem(key, value) {
    prefs.set(key, String(value))
  },
}

const { ACTIONS } = await import('../src/input/actions.js')
const { GamepadService } = await import('../src/input/gamepad.js')

function makePad(pressed = [], axes = [0, 0, 0, 0]) {
  const active = new Set(pressed)
  return {
    buttons: Array.from({ length: 17 }, (_, i) => ({
      pressed: active.has(i),
      value: active.has(i) ? 1 : 0,
    })),
    axes,
  }
}

function recorder(service) {
  const seen = []
  service._run = (ids) => seen.push(ids[0])
  return seen
}

test('D-pad line navigation repeats after the initial press', () => {
  const service = new GamepadService()
  const seen = recorder(service)
  const down = makePad([13])

  service._poll(down, 100, 16)
  service._poll(down, 349, 16)
  service._poll(down, 350, 16)

  assert.deepEqual(seen, ['NAV_NEXT', 'NAV_NEXT'])
})

test('the Back + D-pad pane-switch chord remains edge-triggered', () => {
  const service = new GamepadService()
  const seen = recorder(service)
  const backAndDown = makePad([8, 13])

  service._poll(backAndDown, 100, 16)
  service._poll(backAndDown, 1000, 16)

  assert.deepEqual(seen, ['FOCUS_PANE_NEXT'])
})

test('action repeat behavior follows a custom binding', () => {
  prefs.set('auditview:gamepad:bindings', JSON.stringify({ NAV_NEXT: ['y'] }))
  const service = new GamepadService()
  const seen = recorder(service)
  const y = makePad([3])

  service._poll(y, 100, 16)
  service._poll(y, 350, 16)

  assert.deepEqual(seen, ['NAV_NEXT', 'NAV_NEXT'])
  prefs.clear()
})

test('default layout prioritizes navigation and selection over text entry', () => {
  assert.deepEqual(ACTIONS.JUMP_EMPTY_PREV.pad, ['lb'])
  assert.deepEqual(ACTIONS.JUMP_EMPTY_NEXT.pad, ['rb'])
  assert.deepEqual(ACTIONS.JUMP_UNREVIEWED_PREV.pad, ['back+lb'])
  assert.deepEqual(ACTIONS.JUMP_UNREVIEWED_NEXT.pad, ['back+rb'])
  assert.deepEqual(ACTIONS.TOGGLE_ANCHOR.pad, ['x'])
  assert.deepEqual(ACTIONS.ADD_NOTE.pad, [])
  assert.deepEqual(ACTIONS.ADD_TODO.pad, [])
})
