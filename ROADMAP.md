# Roadmap

## Near term

### VCS / trusted snapshot
The foundational missing piece. Once 100% coverage is reached on a codebase, that state should be anchored to a specific commit and marked as trusted. Future review sessions initialize from the delta: checkout the trusted commit, checkout the target version, run the reconciler — only changed lines need review.

This makes the reconciler's job much smaller (in-progress edits only) and makes the "reviewed" claim honest and reproducible.

### AI agent review platform
Agents reviewing and fixing code is already happening in practice. The gap is the human oversight layer — a clear view of what agents flagged, what they changed, and what still needs human eyes. This is primarily a UI problem: surface agent activity (what session opened what, what was resolved and by whom) alongside human review state.

## Medium term

### Expand automated coverage
The backend has focused tests for core hashing, counting, scanning, reconciliation,
watchers, the CLI, LSP lifecycle, REST/MCP behavior, and SSE payloads, alongside the
reconciler fuzzer. The frontend covers the gamepad state machine and pure navigation
helpers. The largest remaining gap is browser-level coverage of the Vue components and
complete review workflows: selecting files, marking ranges, creating notes and issues,
and reacting to watcher events. Add component and end-to-end tests before expanding the
UI surface further.

### Complete issue lifecycle attribution
The issue tracker now supports open, resolved, and dismissed states; attached line notes;
severity; markdown descriptions; and free-form `source` / `closed_by` attribution. To
support a mixed human/agent workflow end to end, it still needs an in-progress state,
independent verification (`verified_by`), and an append-only transition history rather
than only the latest closer. That would let agents open findings, humans triage them, and
another human or agent resolve and verify them without losing the audit trail.

### Gamepad remapping and wider coverage
Gamepad support ships with a fixed default binding table (standard/Xbox mapping) plus `localStorage` overrides for both the action→button map and the physical input map. Missing: a remap UI that captures a button press and assigns it to an action; bindings for the issues view, which has no keyboard handling either; expanding and collapsing directories in the file tree from the pad (`TreeNode.vue` keeps `expanded` as per-node local state, unaddressable from outside); focus for the orphan-notes panel. `IssuesView`'s delete confirmation uses a native blocking `confirm()`, which no input layer can drive.

### Neovim client
An MVP exists. The nvim plugin is a real daily-driver client and quality here directly affects workflow. Needs sharpening: mark/unmark reliability, cache invalidation, display of notes and coverage inline.

### Symbol navigation beyond go-to-definition
Go-to-definition ships (`--lsp`, ctrl/cmd+click). The earlier framing of this as
"complex to build in-browser, requires an LSP-over-HTTP bridge" was wrong on both
counts: it is a backend LSP client, and the frontend half is small — jump-to-location
and the `g` key prefix already existed. See CLAUDE.md §Architecture for the design and
`scripts/lsp-spike/` for the validated server configurations.

What is deliberately not built yet, roughly in value order:

- **Find references, with review coverage.** "This function has 7 callers, 3 unreviewed"
  is the one thing an editor cannot tell you, and it feeds `audit-triage` directly. The
  blocker is real: there is no per-line "is this reviewed?" lookup anywhere. Coverage is
  read only in aggregate (`core/progress.py`), and because state is keyed on
  `(line_hash, context_hash, line_no)` a faithful answer must read and re-hash every
  referenced file. A `line_no`-only query would be wrong. Needs a new batch helper in
  `core/progress.py`, plus a third panel in `.right-panels`.
- **Plain find references**, without the coverage join — much cheaper, and a useful
  stepping stone if the batch helper proves awkward.
- **A column cursor, and with it `gd`/`gr`.** The cursor is line-only today, so a
  keyboard chord cannot disambiguate which symbol on a line is meant. Doing this
  properly means rendering a cursor inside `v-html` content and should arrive together
  with `w`/`b`/`e` motions. The `g` prefix is being kept free for it.
- **Document outline panel.** Works for Go and Python, but `documentSymbol` returns
  nothing for `.vue` through vtsls, so it cannot be the uniform entry point that
  clicking is.
- **Semantic tokens.** Would replace highlight.js for supported files and delete
  `splitHighlightedLines` — the hand-rolled span-reopening HTML splitter — since the
  payload is already line-relative.

## Later

### Snapshot diff comparison
Follows naturally from trusted snapshots. Compare any two tagged versions, not just "trusted vs HEAD". Useful for auditing a dependency update or a large refactor without starting from zero.

### Reconciliation undo / changeset log
The original apsw-based backend wrapped every reconciliation in a changeset (apsw session extension) and stored it in a `checkpoints` table, allowing revert at the DB level without the app. This was dropped during the Flask→Quart migration because apsw's synchronous driver doesn't compose cleanly with asyncio. The design goal — protecting review history from a reconciler bug — is still valid; a re-implementation would need to work without apsw (e.g. manual before/after snapshots or a WAL-based approach).

## Explicitly out of scope

- **Attestation artifacts** — generating signed audit certificates. Useful in enterprise contexts but not the core use case.
- **Multi-reviewer assignment** — files are not a good boundary for dividing review work. Coordination at this level belongs in a separate tool.
