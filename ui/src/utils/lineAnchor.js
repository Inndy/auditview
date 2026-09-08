// Anchoring a view to a line by content rather than by line number.
//
// When a watched file changes on disk the UI reloads it, and every line number
// past the edit may have moved. Restoring the previous view therefore has to
// re-find the line the user was looking at, not the number it used to have.
// Identity is content-based, mirroring the reconciler: `line_hash` is the line's
// own content, `context_hash` covers prev+curr+next.

export function lineIdentity(lines, lineNo) {
  const line = lines.find((l) => l.line_no === lineNo)
  if (!line) return null
  return { lineNo, lineHash: line.line_hash, contextHash: line.context_hash }
}

// Find `ident` in freshly loaded `lines`, or null when that line is no longer
// present. Prefers a full (content + context) match, then falls back to content
// alone — the common case where an edit to a neighbour invalidated the context
// but left the anchor line itself untouched. Duplicate candidates (a bare `}`)
// are broken by proximity to the line's old position.
export function relocateLine(lines, ident) {
  if (!ident) return null
  let exact = null
  let byContent = null
  for (const line of lines) {
    if (line.line_hash !== ident.lineHash) continue
    const dist = Math.abs(line.line_no - ident.lineNo)
    if (byContent === null || dist < byContent.dist) byContent = { lineNo: line.line_no, dist }
    if (line.context_hash !== ident.contextHash) continue
    if (exact === null || dist < exact.dist) exact = { lineNo: line.line_no, dist }
  }
  return (exact || byContent)?.lineNo ?? null
}
