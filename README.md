# auditview

A line-level code review and audit tool. Track review coverage across an entire codebase, survive live edits, and annotate with notes — until every line has been seen by a human.

## Why this exists

Vibe-coded projects are fast to build but hard to trust. LLM-generated code can have subtle bugs, bad patterns, or security issues that only become visible on careful reading. There was no good tool for systematically tracking "have I actually read this line?" across a whole codebase.

**auditview** was built to fill that gap. The workflow it enables:

1. Open a project directory in auditview.
2. Review lines — mark them as reviewed, leave notes, flag issues.
3. Reach 100% coverage.
4. Announce the project as *"AI-generated, 100% reviewed by human"* — not just vibe coded.

This matters for security engineers auditing unfamiliar codebases, and for developers who want to take ownership of code they didn't write line by line.

## Core concept: review coverage

Coverage is the primary metric — reviewed lines / countable lines. Blank lines and (optionally) comment-only lines are excluded. The goal is a clear, honest percentage that means "a human has read this."

Review state is **content-based, not line-number-based**. When files change, the reconciler migrates marks to their new positions on a best-effort basis. The invariant is strict: a line is never falsely marked as reviewed. Ambiguous cases are dropped rather than migrated.

## Roadmap direction

**VCS integration** — once 100% coverage is reached, a snapshot of that state can be tagged as a trusted version. Future changes then reduce to a `git diff` against the trusted tag — only the delta needs review. Line-level reconciliation becomes unnecessary for stable, version-controlled codebases.

**Human + AI collaboration** — the MCP endpoint allows AI agents to read file state, leave comments, create and resolve issues, and participate in the review process alongside humans. The long-term vision is a platform where humans and agents review code together, with full audit trails.

## See also

- [`SPEC.md`](SPEC.md) — detailed specification: data model, reconciliation rules, API design
- [`API.md`](API.md) — HTTP API reference for the backend
- [`AGENTS.md`](AGENTS.md) — MCP and agent integration guide
