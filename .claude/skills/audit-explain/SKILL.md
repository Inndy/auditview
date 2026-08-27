---
description: Answer a question about how a feature works by tracing the code, then record the answer in auditview as a walkthrough issue whose notes anchor each step to the real source lines. Use when the user asks how something is implemented, where a code flow goes, or asks for a guided tour of a subsystem they can click through later.
allowed-tools: Bash, Read, Grep, Glob
---

# Explain a code flow as a clickable walkthrough

The user asks how something works. You trace it, then leave the answer behind as a **walkthrough
issue**: one auditview issue holding the narrative, plus one note per step anchored to the exact
lines. Opening that issue in the web UI shows every step's source inline, in order.

The point is durability. A chat answer scrolls away; a walkthrough issue stays pinned to the code
and survives edits via auditview's line reconciliation.

## Step 1 — confirm the context

```bash
auditview context
```

Check `root_path` matches the repository. If no session is active, ask the user to activate one
in the web UI and stop.

## Step 2 — trace the flow properly

Read the code before writing anything. Follow the actual path — entry point, each hop, the
terminal state. Note the line ranges as you go; you will need exact `start_line`/`end_line` for
each step.

Include the parts that are easy to miss: error paths, the place where a value crosses a thread
or process boundary, the spot where something is silently dropped. A walkthrough that only shows
the happy path is a worse artifact than no walkthrough.

## Step 3 — create the issue

Use the auditview MCP tools.

```
create_issue(
  title="[flow] <what this walkthrough explains>",
  severity="P2",
  source="agents:explain",
  description=<the narrative, in markdown>,
)
```

- `source="agents:explain"` is what marks this as a walkthrough rather than a defect. The UI
  reads that prefix to show a `flow` badge and dim the severity. Do not omit it.
- `severity` is meaningless for a walkthrough. Always `P2`.
- `description` carries the overall story: what the flow does, where it starts and ends, what
  surprised you. Markdown renders in the UI.

## Step 4 — attach one note per step, in flow order

```
create_note(
  file_path="<relative path>",
  start_line=<n>, end_line=<m>,
  content="<what this step does and why it matters>",
  issue_id=<the issue id>,
)
```

**Creation order is reading order.** The UI lists an issue's notes by creation time, so create
them in the order a reader should walk them — not grouped by file, not sorted by path. This is
the whole mechanism; get it wrong and the tour is scrambled.

Other guidance:

- Keep each range tight — the function or block that makes the point, not the whole file. The
  snippet is rendered inline, so a 200-line range makes the walkthrough unreadable.
- `content` explains *this step*. Do not restate the overall narrative from `description`.
- Six to twelve steps suits most flows. If you need thirty, the question was too broad — say so
  and offer to split it into several walkthroughs.

## Step 5 — report back

Tell the user the issue number and give them the short version of the answer in chat too. They
should not have to open the UI to learn what you found — the issue is the durable copy, not the
only copy.

## Hard rules

- **Never mark lines reviewed.** Coverage records what the *human* has examined. Tracing code to
  explain it is not reviewing it on their behalf.
- **Do not open findings as walkthroughs.** If tracing turns up a real defect, that is a separate
  issue with a real severity and no `agents:explain` source. Say so; do not bury a bug inside a
  tour.
- **Anchor to what you actually read.** Every note's line range must be one you opened and
  verified. A walkthrough with wrong line numbers is worse than none.
