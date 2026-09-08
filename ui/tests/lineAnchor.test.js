import assert from 'node:assert/strict'
import test from 'node:test'

import { lineIdentity, relocateLine } from '../src/utils/lineAnchor.js'

// Build the line shape GET /files returns, with the hashes stood in for by the
// content itself so a fixture reads as the file it represents.
function makeLines(contents) {
  return contents.map((content, i) => ({
    line_no: i + 1,
    content,
    line_hash: `h:${content}`,
    context_hash: `c:${contents[i - 1] ?? ''}|${content}|${contents[i + 1] ?? ''}`,
  }))
}

const FILE = makeLines(['import os', '', 'def main():', '    return 1', '', 'main()'])

test('an unchanged file relocates every line onto itself', () => {
  for (const line of FILE) {
    const ident = lineIdentity(FILE, line.line_no)
    assert.equal(relocateLine(FILE, ident), line.line_no)
  }
})

test('a line pushed down by an insertion above is found at its new number', () => {
  const ident = lineIdentity(FILE, 3) // 'def main():'
  const edited = makeLines([
    'import os',
    'import sys',
    '',
    'def main():',
    '    return 1',
    '',
    'main()',
  ])
  assert.equal(relocateLine(edited, ident), 4)
})

test('a line pulled up by a deletion above is found at its new number', () => {
  const ident = lineIdentity(FILE, 4) // '    return 1'
  const edited = makeLines(['def main():', '    return 1', '', 'main()'])
  assert.equal(relocateLine(edited, ident), 2)
})

test('an edited neighbour breaks the context but the line is still found', () => {
  const ident = lineIdentity(FILE, 4) // '    return 1', its context spans 'def main():'
  const edited = makeLines(['import os', '', 'def main(argv):', '    return 1', '', 'main()'])
  assert.equal(relocateLine(edited, ident), 4)
  // ...and only via the content fallback: the context really did change.
  assert.notEqual(lineIdentity(edited, 4).contextHash, ident.contextHash)
})

test('a line whose own content changed is reported missing', () => {
  const ident = lineIdentity(FILE, 4) // '    return 1'
  const edited = makeLines(['import os', '', 'def main():', '    return 2', '', 'main()'])
  assert.equal(relocateLine(edited, ident), null)
})

test('context picks the right one of two identical lines', () => {
  const dup = makeLines(['if a:', '    pass', 'if b:', '    pass'])
  assert.equal(relocateLine(dup, lineIdentity(dup, 2)), 2)
  assert.equal(relocateLine(dup, lineIdentity(dup, 4)), 4)
})

test('identical lines with identical context fall back to the nearest position', () => {
  // Line 2 is flanked by 'pass' on both sides, so its context does not single it
  // out. After an insertion above it should be found one row down, not at 2 or 4.
  const dup = makeLines(['    pass', '    pass', '    pass'])
  const ident = lineIdentity(dup, 2)
  const edited = makeLines(['if a:', '    pass', '    pass', '    pass'])
  assert.equal(relocateLine(edited, ident), 3)
})

test('a missing line number yields no identity, and no identity relocates to null', () => {
  assert.equal(lineIdentity(FILE, 99), null)
  assert.equal(relocateLine(FILE, null), null)
  assert.equal(relocateLine([], lineIdentity(FILE, 1)), null)
})
