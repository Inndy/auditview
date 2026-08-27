---
description: Recommend which parts of the codebase to review next, using auditview's review-coverage data plus your own reading of the code. Use when the user asks what to review next, where to focus an audit, or which areas are still unexamined.
allowed-tools: Bash, Read, Grep, Glob
---

# Recommend what to review next

Auditview tracks which lines a human has actually reviewed. It does **not** know which code
matters. That judgement is yours, and it is the entire value of this skill: coverage tells you
where attention has *not* gone, you decide where attention *should* go.

## Step 1 — confirm the context

```bash
auditview context
```

Check that `root_path` is the repository you are working in. If it is not, or if the command
reports no active session, stop and ask the user to activate the right session in the auditview
web UI. Do not guess with `--session`.

## Step 2 — pull the coverage data

```bash
auditview stats
auditview files --status not_viewed --status partial --sort size --json
```

`files` returns one row per file: `rel_path`, `countable_lines`, `reviewed_lines`, `coverage`,
`status`, `notes_count`, `todos_count`, `max_severity`, `open_issue_count`.

These are facts about attention, not about importance. A 2000-line lockfile at 0% coverage is
not a finding.

## Step 3 — actually read the candidates

This is the part you cannot skip. Narrow the list, then open the files and skim them. Ask:

- **Blast radius** — what breaks if this is wrong? What else imports or calls it?
- **Attack surface** — does it parse untrusted input, touch the filesystem or network, build
  paths, shell out, deserialize, or construct queries?
- **Invariants under load** — concurrency, ordering, partial failure, resource cleanup.
- **Recent churn** — `git log --oneline -20 -- <path>` if you want change history; recently
  rewritten code is under-scrutinised code.
- **Neighbourhood** — files with existing notes or open issues often have more nearby.

Use `Grep` and `Read` freely. Cross-reference `auditview files --json` against what you find.

## Step 4 — report

Give the user an ordered shortlist, typically 3–7 entries. For each:

- the file, and the specific region or function worth opening first
- **why it matters** — in your own words, from what you read, not from the coverage number
- what to look for when they get there
- current coverage, as context rather than as justification

Rank by consequence, not by percentage. Say plainly when a large uncovered file is not worth
reviewing (generated code, lockfiles, vendored dependencies, fixtures) — pruning the list is as
useful as ranking it.

## Hard rules

- **Never mark lines reviewed.** Coverage is the human's record of what *they* have examined.
  An agent writing to it destroys the only signal this skill depends on. There is no CLI
  subcommand for marking, and you must not reach for the API or MCP to do it either.
- **Write nothing.** This skill produces a recommendation for a person to act on. Do not create
  issues or notes. If you found a concrete defect while reading, say so in your report and offer
  to record it — use `audit-explain` or the auditview MCP tools only after the user agrees.
- **Do not invent a score.** No weighted formula, no numeric priority. Reasons in prose.
