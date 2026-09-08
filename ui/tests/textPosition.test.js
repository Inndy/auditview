import assert from 'node:assert/strict'
import test from 'node:test'

import { wordRangeAt } from '../src/utils/textPosition.js'

// wordRangeAt drives only the ctrl/cmd+hover underline, so it is deliberately a
// regex over the raw line rather than anything the language server provides.
// It is also the one piece of the click path that needs no DOM, so it is the
// piece worth testing here; columnFromPoint and rangeForColumns are covered by
// the backend's known-good positions end to end.

test('finds the identifier under the column', () => {
  const line = "import LineGutter from './LineGutter.vue'"
  const [start, end] = wordRangeAt(line, 8)
  assert.equal(line.slice(start, end), 'LineGutter')
})

test('works at either boundary of the identifier', () => {
  const line = 'const count = ref(0)'
  assert.deepEqual(wordRangeAt(line, 6), [6, 11]) // on the 'c'
  assert.deepEqual(wordRangeAt(line, 11), [6, 11]) // just past the 't'
})

test('includes $ and _ but not dots or dashes', () => {
  assert.equal(
    (() => {
      const l = 'this.$refs.cell_1'
      const [s, e] = wordRangeAt(l, 12)
      return l.slice(s, e)
    })(),
    'cell_1',
  )
  const line = 'a.$b'
  const [s, e] = wordRangeAt(line, 2)
  assert.equal(line.slice(s, e), '$b')
})

test('returns null on whitespace not adjacent to an identifier', () => {
  assert.equal(wordRangeAt('a = b', 2), null) // on the '='
  assert.equal(wordRangeAt('({})', 1), null)
  assert.equal(wordRangeAt('    ', 2), null)
})

test('a column immediately after an identifier still resolves to it', () => {
  // Deliberate: the caret lands between characters, so the position just past
  // the last character of a symbol is still a click "on" it. This makes the
  // underline forgiving at the right-hand edge instead of flickering off.
  const line = 'a = b'
  const [start, end] = wordRangeAt(line, 1)
  assert.equal(line.slice(start, end), 'a')
})

test('handles the very end of the line', () => {
  const line = 'onMouseDown'
  assert.deepEqual(wordRangeAt(line, line.length), [0, 11])
})

test('rejects out-of-range and non-string input', () => {
  assert.equal(wordRangeAt('abc', -1), null)
  assert.equal(wordRangeAt('abc', 4), null)
  assert.equal(wordRangeAt('abc', null), null)
  assert.equal(wordRangeAt(null, 0), null)
})

test('counts UTF-16 code units, matching DOM offsets and LSP', () => {
  // An emoji is two code units, so a naive per-codepoint walk would land the
  // identifier two columns early -- and the backend passes this straight to the
  // language server without conversion.
  const line = "const s = '🎉' // tag_name"
  const idx = line.indexOf('tag_name')
  const [start, end] = wordRangeAt(line, idx)
  assert.equal(line.slice(start, end), 'tag_name')
  assert.equal(start, idx)
})
