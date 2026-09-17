import assert from 'node:assert/strict'
import test from 'node:test'

const { ownsKeyNatively } = await import('../src/input/keyboard.js')

function press(key, el, mods = {}) {
  return {
    key,
    ctrlKey: false,
    metaKey: false,
    altKey: false,
    ...mods,
    target: { closest: () => el },
  }
}

const checkbox = { tagName: 'INPUT', type: 'checkbox' }
const button = { tagName: 'BUTTON' }
const textInput = { tagName: 'INPUT', type: 'text' }
const textarea = { tagName: 'TEXTAREA' }
const select = { tagName: 'SELECT' }
const radio = { tagName: 'INPUT', type: 'radio' }

test('motion keys stay live while a checkbox or button holds focus', () => {
  for (const el of [checkbox, button]) {
    assert.equal(ownsKeyNatively(press('j', el)), false)
    assert.equal(ownsKeyNatively(press('k', el)), false)
    assert.equal(ownsKeyNatively(press('?', el)), false)
    assert.equal(ownsKeyNatively(press('d', el, { ctrlKey: true })), false)
  }
})

test('activation keys still belong to the focused control', () => {
  assert.equal(ownsKeyNatively(press(' ', checkbox)), true)
  assert.equal(ownsKeyNatively(press('Enter', button)), true)
})

test('arrow keys belong to a radio group but not to a checkbox', () => {
  assert.equal(ownsKeyNatively(press('ArrowDown', radio)), true)
  assert.equal(ownsKeyNatively(press('ArrowDown', checkbox)), false)
})

test('anything with a caret or typeahead owns the whole keyboard', () => {
  for (const el of [textInput, textarea, select, { isContentEditable: true, tagName: 'DIV' }]) {
    assert.equal(ownsKeyNatively(press('j', el)), true)
  }
})

test('a key with no interactive element in scope is never native', () => {
  assert.equal(ownsKeyNatively(press('j', null)), false)
  assert.equal(ownsKeyNatively({ key: 'j', target: null }), false)
})
