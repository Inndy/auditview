# auditview

Track human code-review coverage line by line for vibe-coded projects and
security audits. Review marks survive ordinary edits, while notes and issues
keep an audit trail beside the code.

> [!IMPORTANT]
> 100% means a human marked every countable line as read. It does **not** prove
> that the code is correct, secure, vulnerability-free, or entirely
> human-written.

## Quick start

auditview requires Python 3.14 or newer. Install the published CLI with
[uv](https://docs.astral.sh/uv/) (recommended) or pipx:

```bash
uv tool install auditview
# or: pipx install auditview
```

Start it against the directory you want to review:

```bash
auditview /path/to/project
```

Open `http://127.0.0.1:5000`, create a session, then select a file. The server
stores review state in `/path/to/project/.auditview.db`; add that file to the
project's ignore rules if it should remain local.

For development from a checkout, use `uv sync --group dev` followed by
`uv run auditview /path/to/project`.

## Why this exists

### Vibe-coded projects

LLM-generated code is fast to build but hard to trust. Subtle bugs, bad patterns, and security issues are only visible on careful reading. **auditview** tracks "have I actually read this line?" across a whole codebase, so you can reach 100% coverage and make a credible claim:

1. Open a project directory in auditview.
2. Review lines — mark them as reviewed, leave notes, flag issues.
3. Reach 100% coverage.
4. Describe the measured scope precisely: *"Every countable line was marked as
   read by a human."*

### Security audit

When auditing an unknown or untrusted codebase, the same workflow applies: systematic line coverage ensures no file goes unseen. Notes and issues become the audit trail. The coverage percentage is an honest measure of how much ground has been covered.

### Reviewing away from the desk

The whole review loop — move the cursor, select a range, mark reviewed, jump between code blocks or unreviewed lines, switch files — is driven by the keyboard, and equally by a game controller. Any pad reporting the standard (Xbox) mapping works, including a Steam Controller or Steam Deck via Steam Input. Note and TODO creation stays keyboard-only until speech input is available, so the default controller layout prioritizes navigation and marking.

## Core concept: review coverage

Coverage is the primary metric — reviewed lines / countable lines. Blank and
comment-only lines are excluded. Binary files and files over 1 MiB remain
visible but stay outside the coverage denominator. The goal is a clear, honest
percentage that means "a human recorded reading this," not a quality score.

Review state is **content-based, not line-number-based**. When files change, the reconciler migrates marks to their new positions on a best-effort basis. The invariant is strict: a line is never falsely marked as reviewed. Ambiguous cases are dropped rather than migrated.

## Querying coverage from the command line

The `auditview` executable also serves a read-only CLI for AI agents and scripts. It reads
`.auditview.db` directly, so the server does not need to be running:

```bash
auditview context   # which session and repository root these commands act on
auditview stats     # session-wide coverage and issue counts
auditview files --status not_viewed --sort size --json
```

The database is found via `--db`, then `$AUDITVIEW_DB`, then by searching upward from the working
directory for `.auditview.db`. The session is chosen via `--session`, then whichever session is
active in the web UI, then the only session if there is exactly one.

These commands report review state and nothing else — there is deliberately no priority score.
Deciding which code matters is the agent's job, informed by reading the code; see the
`audit-triage` and `audit-explain` skills under `.claude/skills/`.

A bare subcommand name anywhere in the arguments routes to the CLI, so `auditview stats` queries
rather than serves. If you need to serve a directory that happens to be named after a subcommand,
use the explicit form: `auditview serve ./stats`.

## Roadmap direction

**VCS integration** — once 100% coverage is reached, a snapshot of that state can be tagged as a trusted version. Future changes then reduce to a `git diff` against the trusted tag — only the delta needs review. Line-level reconciliation becomes unnecessary for stable, version-controlled codebases.

**Human + AI collaboration** — the MCP endpoint allows AI agents to read file state, leave comments, create and resolve issues, and participate in the review process alongside humans. The long-term vision is a platform where humans and agents review code together, with full audit trails.

## Integrations

### MCP agents

With the server running, select an MCP target session on the home page and
connect the agent to the Streamable HTTP endpoint:

```json
{
  "mcpServers": {
    "auditview": {
      "type": "http",
      "url": "http://127.0.0.1:5000/mcp"
    }
  }
}
```

The human must activate a session first. Agents can read coverage and create
notes or issues, but review coverage remains the human's ledger: agents must
not mark lines reviewed.

### Neovim

The bundled [Neovim plugin](nvim/README.md) shows review state, notes, and TODOs
inside buffers and sends marking actions to the same local server.

## Running safely

auditview is designed for single-user, single-instance use on a trusted local machine. There is no authentication layer — all endpoints are open to any client that can reach the bound address. Do not expose the server port to untrusted networks.

### Language servers and untrusted code

Symbol navigation (`--lsp`, off by default) spawns language servers found on
`PATH` against the tree you are auditing. Analysing code is not the same as
merely reading it: `tsserver` loads `tsconfig.json` plugins from
`node_modules`, and `rust-analyzer` runs `build.rs` and proc macros. If the
codebase under review is untrusted, that is a meaningful difference — which is
why the flag is opt-in rather than default. `gopls` is spawned with
`GOFLAGS=-mod=readonly` and `GOPROXY=off` so analysis cannot rewrite `go.mod`
or fetch modules.

Definitions that land outside the session root are readable through a preview
endpoint that serves only paths a query actually returned, and that writes
nothing — an external file can never be marked reviewed, so coverage keeps
meaning "a human read *this* project".

## See also

- [`API.md`](API.md) — HTTP API reference for the backend
- [`AGENTS.md`](AGENTS.md) — coding agent guide (alias for CLAUDE.md)
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — development workflow
- [`SECURITY.md`](SECURITY.md) — supported versions and threat model
- [`ROADMAP.md`](ROADMAP.md) — planned work
