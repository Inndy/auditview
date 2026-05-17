---
description: Study the codebase and generate or update project-specific code review lenses. Each lens defines a focused traversal strategy (entry point, what to follow, what to hunt for).
argument-hint: "[lens-name-to-update] (optional — omit to regenerate all)"
allowed-tools: Read, Write, Glob, Grep
---

# Code Review Strategy Builder

## What To Do With This Skill

- You should create or update existed per-project skills (~/path/to/project/.claude/skills)
- Each skill is a codeview "lens", let's name they with prefix "codeview-lens-"
- You should understand overall project structure and identify major components
- Use parallel subagents (Task tool) to survey each major component simultaneously.
- Briefly explain why we need agents to survey codebase (to create codereview strategy)
- Each subagent should report back the component's responsibility, key data structures, and entry points.

## Core Insight

A single "review this code" pass distributes attention evenly and catches nothing deeply.
Effective review = multiple **focused traversals**, each with a different starting point and a different question.

## What a Review Lens Looks Like

Each lens defines:
- **Entry point** — where to start reading (not always the top of the file)
- **What to follow** — the "edge" you traverse (data flow, goroutine access, error paths, call chains)
- **What to ask at each node** — the specific failure mode you're hunting

## Your Task

1. **Study the codebase structure first.** Identify:
   - What are the major subsystems / packages?
   - Where does external data enter the system?
   - Where is shared mutable state?
   - What are the critical paths (latency-sensitive, security-sensitive, frequently called)?

2. **Derive 4–6 project-specific review lenses.** Generic lenses are a starting point, not the answer. Tailor them to what this codebase actually does.

   Common lens archetypes to adapt:
   | Lens | Entry Point | Follow | Hunt For |
   |------|-------------|--------|----------|
   | Data flow | API / input boundary | transformations & copies | unnecessary allocations, lossy conversions, implicit trust |
   | Concurrency | shared state / globals | all goroutine access points | missing locks, wrong lock granularity, channel misuse |
   | Error propagation | fallible calls | error return paths | swallowed errors, inconsistent handling, missing context |
   | Dependency audit | import list | each external call site | replaceable with stdlib, inactive/untrusted packages |
   | Trust boundary | external inputs | data path into sensitive operations | missing validation, privilege confusion |

3. **Write each lens as a self-contained review instruction**, structured as:
   ```
   ### Lens: <name>
   **Why this matters for this codebase:** <one sentence>
   **Start at:** <specific files, interfaces, or patterns>
   **Follow:** <what you trace>
   **Look for:** <concrete failure patterns, not vague "bugs">
   ```
4. **After drafting per-component lenses, derive cross-component lenses.**
   With all subagent reports in hand, ask:
   - What crosses component boundaries? (data, errors, events, goroutines)
   - Where does ownership hand off — and is the contract explicit?
   - Which failure modes only appear when two specific components interact?

   These become your highest-value lenses because no single component owner would catch them.

## Principles to Apply Throughout

- When you find a defensive guard (`if err`, boundary check, type assertion guard), ask: *is this patching a symptom, or is the data model wrong?*
- Prefer finding the **root shape of a bug class** over listing individual instances.
- Flag where the code forces the reader to hold context across distant locations — that's a design smell, not just a readability issue.
- Absence of a lens is a finding too: if concurrency exists but no clear ownership model is documented, say so.
- If a name needs a comment to clarify what it means, the name is wrong. Flag identifiers that leak implementation detail, lie about scope, or force the reader to look elsewhere to understand intent.
- Distinguish between *validating* illegal state and *preventing* it. A guard that checks for an impossible condition is a sign the type or data model should make that state unrepresentable in the first place.
- Flag functions that do more than one thing. The test: can you describe what it does without using "and"? If not, it's a composition candidate, not a refactor target.
- Question every abstraction that adds indirection without reducing complexity. More code is not more safety — it's more surface area. Flag abstractions where the wrapper is harder to reason about than what it wraps.
