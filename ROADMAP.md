# Roadmap

## Near term

### VCS / trusted snapshot
The foundational missing piece. Once 100% coverage is reached on a codebase, that state should be anchored to a specific commit and marked as trusted. Future review sessions initialize from the delta: checkout the trusted commit, checkout the target version, run the reconciler — only changed lines need review.

This makes the reconciler's job much smaller (in-progress edits only) and makes the "reviewed" claim honest and reproducible.

### AI agent review platform
Agents reviewing and fixing code is already happening in practice. The gap is the human oversight layer — a clear view of what agents flagged, what they changed, and what still needs human eyes. This is primarily a UI problem: surface agent activity (what session opened what, what was resolved and by whom) alongside human review state.

## Medium term

### Unit tests
Currently only the reconciler fuzz suite exists. Core business logic in `auditview/core/` has no unit tests. Adding targeted tests for the reconciler, scanner, and session management would catch regressions earlier and reduce reliance on fuzzing as the only safety net.

### Issue lifecycle with attribution
Notes and TODOs exist but are informal. A lightweight issue tracker — open → in progress → resolved — with `opened_by`, `resolved_by`, `verified_by` fields turns the tool into a coordination platform for mixed human/agent review workflows. Agents can open issues on suspicious lines; humans triage; other agents or humans resolve and verify.

### Neovim client
An MVP exists. The nvim plugin is a real daily-driver client and quality here directly affects workflow. Needs sharpening: mark/unmark reliability, cache invalidation, display of notes and coverage inline.

## Later

### LSP integration
Symbol-aware navigation within the review UI — jump to definition, find references, understand call graphs without leaving the tool. Complex to build in-browser (requires an LSP-over-HTTP bridge). The nvim client already gets this for free from the editor; in-browser LSP is a longer-term investment.

### Snapshot diff comparison
Follows naturally from trusted snapshots. Compare any two tagged versions, not just "trusted vs HEAD". Useful for auditing a dependency update or a large refactor without starting from zero.

### Reconciliation undo / changeset log
The original apsw-based backend wrapped every reconciliation in a changeset (apsw session extension) and stored it in a `checkpoints` table, allowing revert at the DB level without the app. This was dropped during the Flask→Quart migration because apsw's synchronous driver doesn't compose cleanly with asyncio. The design goal — protecting review history from a reconciler bug — is still valid; a re-implementation would need to work without apsw (e.g. manual before/after snapshots or a WAL-based approach).

## Explicitly out of scope

- **Attestation artifacts** — generating signed audit certificates. Useful in enterprise contexts but not the core use case.
- **Multi-reviewer assignment** — files are not a good boundary for dividing review work. Coordination at this level belongs in a separate tool.
