---
description: Review trust boundaries — there is no authentication; the model rests on session_id in the URL, safe_path() for filesystem access, and an MCP loopback that trusts an active-session config. Use when touching any route that takes a path, a session_id, or a markdown body, and any time MCP/config changes.
allowed-tools: Read, Glob, Grep
---

# Lens: trust boundary & session isolation

**Why this matters for this codebase:** Auditview has no authn/authz layer. The entire trust model is: (a) `session_id` from the URL path identifies the data; (b) `safe_path()` confines filesystem access to a session's root; (c) the MCP endpoint loops back through the test client using whatever session was configured via `PUT /api/config/mcp-session`. Each piece is small. Composed, they create privilege-confusion surfaces — cross-session writes, symlink escapes, and untrusted markdown rendered in another user's browser.

## Start at

- `auditview/api/util.py` → `safe_path(root, rel)` — the single chokepoint. Confirm what it accepts, what it rejects, and what it returns on rejection.
- Every blueprint in `auditview/api/`:
  - `sessions.py`, `files.py`, `lines.py`, `notes.py`, `issues.py`, `coverage.py`, `events.py`, `config.py`, `mcp.py` — grep for `safe_path`, `session_id`, `rel_path`, `file_path`, `os.path`, `realpath`, `open(`.
- `auditview/api/config.py`:
  - `POST /api/config/resolve-path` — takes a path, returns realpath. Confine within root, or returns absolute paths anywhere?
  - `PUT /api/config/mcp-session` — sets which session MCP tools operate on.
- `auditview/api/mcp.py`:
  - `_SessionAPI._call()` → `quart_app.test_client()` — the loopback. How is the session_id resolved per call?
- `ui/src/markdown.js` + every `v-html` site in `ui/src/components/` and `ui/src/views/` — the content-rendering trust boundary.

## Follow

For each route: trace from request arrival → which parameters came from where (URL path, body, query, headers) → which one selects the session → which path inputs reach the filesystem → whether `safe_path` was called. Then, for MCP: from MCP tool input → SessionAPI selects session_id via config → loopback request → does the looped-back route revalidate, or does it trust the session that was selected upstream? Then, for markdown: from note body persistence → API response → `renderMarkdown()` → `v-html`.

## Look for

- **Routes that touch the filesystem without `safe_path`**: any `open()`, `os.path.join(root, …)`, or `Path(root) / …` that isn't gated by `safe_path`. Especially in `files.py` (rescan), `coverage.py`, and `config.py:resolve-path`.
- **`/config/resolve-path` symlink escape**: `os.path.realpath()` resolves symlinks but the result must still be confined under the session root. Confirm a follow-up check; absence is a directory-traversal primitive.
- **Cross-session writes via body fields**: routes that take `session_id` from the URL but also accept a `session_id` (or `file_path` rooted in another session) in the body — body data must never override URL identity. Check `notes.py`, `issues.py`, MCP `create_note`/`create_issue`.
- **No ownership check on session access**: any client can open any session by guessing or enumerating IDs. If the threat model treats sessions as private to whoever started the server, document it; if multi-user is ever in scope, this is the gap.
- **MCP "active session" trust window**: a tool call reads the active session from `/api/config`, then issues a looped-back call. Between read and call, the active session can change. Worse: an attacker who can write to `/api/config/mcp-session` can redirect every subsequent MCP tool to a different session. Confirm config is *not* writable by untrusted local processes (e.g. another tool on the same host hitting localhost:5000).
- **`test_client` loopback context inheritance**: confirm the looped request doesn't inherit `request`/`g`/`current_app` state from the outer request in a way that grants the inner call additional authority.
- **Markdown XSS via `v-html`**: `markdown.js` sets `html: false` and adds `rel="noopener noreferrer nofollow" target="_blank"` to links. Verify (a) no other component calls `v-html` on raw user input bypassing `renderMarkdown`, (b) `markdown-it` plugins / future flags don't re-enable HTML, (c) no `javascript:` URL bypass on links (markdown-it normalizes by default — confirm it's not disabled).
- **Reflective fields**: notes' `body`, issues' `description`, snapshot text rendered in the nvim detail view — all flow into rendered markdown surfaces. Anywhere a `data:` or `javascript:` URI could be injected and rendered.
- **`File path` reflected to clients**: error responses that include a resolved absolute path can leak server filesystem layout — minor but worth noting.
- **CORS / Host headers**: the server binds to a configurable address. Confirm CORS isn't `*` and Host isn't validated leniently — local web pages should not be able to drive the API.
- **Path encoding**: URL-encoded `..` or NUL bytes — does `safe_path` decode and check, or check then decode?

## Diagnostic heuristic

For every parameter that influences which file is read or which session is mutated, write down its **source** (URL / body / config / MCP context) and its **validation site**. Any path where the parameter source is "body or config" and the validation site is "none" is the finding.

## Universal review principles

Apply these across every lens, in addition to the lens-specific items above:

- A defensive guard (`if err`, boundary check, type-assertion guard) is a question, not an answer: *is this patching a symptom, or is the data model wrong?*
- Find the **root shape of a bug class**, not individual instances.
- Code that forces the reader to hold context across distant locations is a design smell, not just a readability issue.
- Absence of a structure is a finding: concurrency without a documented ownership model, an API without a documented error shape, a cache without a documented invalidation rule.
- If a name needs a comment to clarify its meaning, the name is wrong. Identifiers that leak implementation detail, lie about scope, or force a reader to look elsewhere are bugs.
- Distinguish *validating* illegal state from *preventing* it. A guard against an "impossible" state is a sign the type or data model should make the state unrepresentable.
- A function that can't be described without "and" is doing more than one thing — composition candidate, not refactor target.
- Question every abstraction that adds indirection without reducing complexity. More code is more surface, not more safety; flag wrappers harder to reason about than what they wrap.

## Related lenses

- Hash trust (client-supplied hashes as DB keys): [[codeview-lens-line-identity]].
- Cache-driven misattribution after external edits: [[codeview-lens-nvim-cache-drift]].
