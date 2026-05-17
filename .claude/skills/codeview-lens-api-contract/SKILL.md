---
description: Audit the HTTP API as a contract shared by three independent consumers (Vue UI, nvim plugin, MCP loopback) against API.md as the declared source of truth. Use whenever you add/change a route, rename a field, change a status code, or ship a feature that should be visible in more than one client.
allowed-tools: Read, Glob, Grep
---

# Lens: API contract & cross-client parity

**Why this matters for this codebase:** The backend serves three consumers — the **Vue UI** (`ui/src/api/*.js`), the **Neovim plugin** (`nvim/lua/auditview/*` over curl), and **MCP tools** (which loop back through the test client). `API.md` is declared in `CLAUDE.md` as the source of truth and "drifts silently otherwise." Three failure classes follow from that: (1) clients diverge from each other — one updated, one not; (2) `API.md` diverges from server reality — the contract documents a fiction; (3) features land in one client but not the others, fragmenting capability so a user's mental model depends on which client they happened to open. None of these break tests (there are none); none surface as runtime errors; they only show up as user confusion when the answer to "is this reviewed?" depends on which window is on top.

## Start at

- `API.md` — the declared contract. Skim section headings to know which routes are documented.
- Backend route surface: `auditview/api/*.py` blueprints — the *actual* contract.
- Vue client: `ui/src/api/*.js` — one file per resource, all through `apiFetch` in `client.js`.
- Nvim client: `nvim/lua/auditview/http.lua` plus every call site (`marks.lua`, `notes.lua`, `buffer.lua`, `session.lua`, `integrations/nvim_tree.lua`).
- MCP client (third consumer): `auditview/api/mcp.py` `_SessionAPI._call` — the looped-back paths.
- Recent feature commits — `git log --oneline -30` — pick the last few non-trivial features and ask "did this land in all three clients?"

## Follow

Two complementary traversals:

1. **Route-major**: pick each route in `API.md` (or each route in the blueprints — see which side is the gap). For that route, locate (a) the backend handler, (b) the UI caller, (c) the nvim caller, (d) the MCP tool. Compare the request body shape, the response shape, the status codes, and the error shape *as each consumer constructs and parses them*. Note any mismatch.

2. **Feature-major**: pick a recent feature visible in `git log` (e.g. "severity-aware sign colors", "focusable note/TODO detail view", "[r/]r jump"). For that feature, walk *all* clients and ask: is the underlying capability reachable from each? Is the response shape adequate for the richer client and parsable by the leaner client?

## Look for

- **Backend routes with no `API.md` entry**: grep `@bp.route` / `@bp.get` / `@bp.post` across `auditview/api/`, cross-reference with `API.md` headings. Undocumented routes are either internal-only (mark them as such in `API.md`) or contract drift in disguise.
- **`API.md` entries with no backend route**: documented but removed or renamed. Reverse drift.
- **Field-name drift between clients**: e.g. the UI sends `body` but nvim sends `text` for a note. The server accepts both via an `or` fallback — and that fallback is the finding, because it lets clients drift further without breaking.
- **Status-code interpretation differences**: UI's `apiFetch` throws an `Error` with the message string and discards the status (per the survey). Nvim's `http.lua` returns `(nil, err_string)`. MCP tool wrappers may pass status through as JSON-RPC error codes. The same 409 from the server can become "Something went wrong" in UI, a `vim.notify` warn in nvim, and a structured JSON-RPC error in MCP — clients can't make the same decision from the same response.
- **Error response shape inconsistency**: the survey already found `{error: str}` is dominant but not universal. Inventory every route's error shape and confirm `API.md` documents one. A consumer that expects `error.code` will silently see `undefined`.
- **Optional-vs-required asymmetry**: a field one client always sends and the other sometimes omits. If the server treats "missing" and "empty string" differently, the two clients produce different DB state. The default-value choice should live in *server* code, not duplicated in every client.
- **Capability gaps (feature parity)**: walk the recent features and confirm propagation. Examples surfaced in the survey:
  - "Severity-aware sign colors" — does the UI render an equivalent severity cue, and does MCP expose severity on `create_note`?
  - "Notes/TODOs buffer rendering" — does the UI have a comparable list, and is the underlying endpoint the same one nvim calls?
  - SSE live updates — UI gets them, nvim doesn't (acknowledged in README). Whenever a new "real-time" feature lands, the asymmetry compounds; flag it explicitly per feature.
- **Pagination / limit defaults**: if any endpoint paginates (or grows to), the *default page size* must be documented in `API.md`, not embedded as a magic number in each client. Otherwise the UI shows N items and nvim shows M for the same endpoint.
- **Boolean coercion / encoding choices**: `?include_orphans=true` vs `1` vs `yes`. URL encoding of paths with spaces, `+` vs `%20`. Confirm each client encodes the same way for the same endpoint.
- **Implicit ordering guarantees**: does the route document a sort order? If not, the UI's "newest first" assumption and nvim's "as returned" rendering will diverge silently the day the server adds a join.
- **MCP-only fields**: MCP tools sometimes need IDs or metadata that aren't useful to UI/nvim. Confirm they're either (a) returned to all consumers harmlessly, or (b) gated behind an MCP-only flag — never silently added to all consumers and quietly relied upon by one.
- **Markdown-body parity**: a note's `body` is rendered by `markdown-it` (`html: false`) in the UI and by `vim.lsp.util.open_floating_preview` (filetype=markdown) in nvim. These are two sanitization/rendering regimes for the same source — links, embedded HTML, and image references behave differently. Cross-link [[codeview-lens-trust-boundary]] for the XSS half; here, the parity finding is that *the same content reads differently* to two users.
- **Pre-commit doc check** (per the project's global instructions): `API.md` updates are obligated on any request/response shape change. If a recent commit changed a route and `API.md` is untouched, the contract is already broken.

## Diagnostic heuristic

When you change anything in `auditview/api/`, write the change down in four columns: **server**, **API.md**, **UI client**, **nvim client** (and optionally **MCP**). Every column that doesn't get a tick is a finding. The absence of a column update is the bug, regardless of whether tests pass.

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

- Wire-level hash semantics that all clients must agree on: [[codeview-lens-line-identity]].
- Which client sees a failure when the server fails: [[codeview-lens-error-propagation]].
- The third consumer (MCP) as a privilege surface, not just an API consumer: [[codeview-lens-trust-boundary]].
- The asymmetry where UI has SSE and nvim doesn't: [[codeview-lens-sse-lifecycle]].
