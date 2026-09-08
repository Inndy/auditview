/**
 * Resolve a click inside a rendered code line to a character column.
 *
 * The line's HTML comes from highlight.js via `v-html`, so the text is split
 * across however many `<span>`s the highlighter produced. Rather than parse
 * that, we ask the browser which caret position the pointer is over and then
 * count text-node lengths up to it.
 *
 * The offsets this returns are UTF-16 code units, because that is what DOM text
 * node offsets are -- and it happens to be exactly what LSP wants by default.
 * No conversion anywhere; converting to a byte offset would break every line
 * containing non-ASCII text.
 *
 * Escaping does not shift anything either: hljs writes `&lt;` but the DOM text
 * node holds the single character `<`, so columns line up with the source.
 */

function caretFromPoint(x, y) {
  // Standard (Firefox) first, then the WebKit/Blink spelling.
  if (document.caretPositionFromPoint) {
    const pos = document.caretPositionFromPoint(x, y);
    return pos ? { node: pos.offsetNode, offset: pos.offset } : null;
  }
  if (document.caretRangeFromPoint) {
    const range = document.caretRangeFromPoint(x, y);
    return range ? { node: range.startContainer, offset: range.startOffset } : null;
  }
  return null;
}

function offsetWithin(root, node, offset) {
  if (node.nodeType === Node.TEXT_NODE) {
    let col = 0;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let n = walker.nextNode();
    while (n) {
      if (n === node) return col + offset;
      col += n.nodeValue.length;
      n = walker.nextNode();
    }
    return null;
  }
  // The caret can land on an element, in which case `offset` is a child index.
  // Sum the text of everything before that child.
  let col = 0;
  for (let i = 0; i < offset && i < node.childNodes.length; i += 1) {
    col += node.childNodes[i].textContent.length;
  }
  let cur = node;
  while (cur && cur !== root) {
    let sib = cur.previousSibling;
    while (sib) {
      col += sib.textContent.length;
      sib = sib.previousSibling;
    }
    cur = cur.parentNode;
  }
  return cur === root ? col : null;
}

/**
 * 0-based column within `cellEl`'s text for a viewport point, or null.
 */
export function columnFromPoint(cellEl, clientX, clientY) {
  if (!cellEl) return null;
  const caret = caretFromPoint(clientX, clientY);
  if (!caret || !caret.node || !cellEl.contains(caret.node)) return null;
  return offsetWithin(cellEl, caret.node, caret.offset);
}

const IDENT = /[A-Za-z0-9_$]/;

/**
 * Bounds of the identifier containing `col`, as `[start, end)`, or null.
 *
 * Deliberately a regex over the raw line rather than anything the server
 * provides: this only drives the hover underline, and an affordance that waits
 * on a round trip is worse than a slightly generous one.
 */
export function wordRangeAt(text, col) {
  if (typeof text !== 'string' || col == null || col < 0 || col > text.length) return null;
  let start = col;
  let end = col;
  while (start > 0 && IDENT.test(text[start - 1])) start -= 1;
  while (end < text.length && IDENT.test(text[end])) end += 1;
  return end > start ? [start, end] : null;
}

/**
 * A DOM Range covering `[start, end)` of `cellEl`'s text, or null.
 *
 * Used with the CSS Custom Highlight API so the hover underline needs no extra
 * elements -- the highlighted line's markup is left exactly as rendered.
 */
export function rangeForColumns(cellEl, start, end) {
  if (!cellEl || start == null || end == null || end <= start) return null;
  const walker = document.createTreeWalker(cellEl, NodeFilter.SHOW_TEXT);
  let col = 0;
  let range = null;
  let n = walker.nextNode();
  while (n) {
    const len = n.nodeValue.length;
    if (range === null && col + len >= start) {
      range = document.createRange();
      range.setStart(n, start - col);
    }
    if (range !== null && col + len >= end) {
      range.setEnd(n, end - col);
      return range;
    }
    col += len;
    n = walker.nextNode();
  }
  return null;
}
