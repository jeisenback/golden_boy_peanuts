# Working Agreement — Energy Options Opportunity Agent
#
# Read this before your first session. Review at every sprint boundary.
# Written for the AI agent team + human lead who develop this repository.
# AI agents are treated as developers: they read this doc, follow its rules,
# ask when uncertain, and explain before making large changes.

## 1. Team Composition and Mode of Operation

This project is developed by a small team of AI coding agents (Claude Code,
Cursor, Copilot) and one human lead. **Agents are treated as developers.**

The human lead owns:
- Architecture decisions not explicitly specified in an issue
- Adding, removing, or changing dependencies
- Merging PRs to `develop` or `main`
- Changing issue scope mid-sprint
- Sprint boundaries (start and close)
- All irreversible git operations
- Any decision that crosses phase boundaries (Phase 1 → Phase 2, etc.)

Agents own:
- Implementation details within a well-scoped issue
- Test authorship (writing tests for their own code)
- Documentation updates within the scope of their current issue
- Code quality: type hints, docstrings, ruff/mypy compliance
- Explaining what they're about to do before doing it (>100 lines — see § 8)

**When in doubt: explain what you're about to do and ask.**

---

## 2. Document Hierarchy (Decision Authority)

When documents appear to conflict, the higher document wins.
Do not deviate from a higher-authority document without explicit human approval.

```
PRD             — what to build and why (docs/energy_options_prd.md)
    ↓
ESOD            — how to build it; all constraints are non-negotiable (docs/energy_options_esod.md)
    ↓
Design Doc      — module boundaries, data flow, schema intent (docs/energy_options_agent_design_doc.md)
    ↓
Working Agreement — team rules; this document
    ↓
CLAUDE.md       — agent operational rules; daily driver
    ↓
Agent judgment  — within the explicit scope of the current issue only
```

**Concrete examples:**
- ESOD says "no `langchain.*`" → no agent judgment overrides this, ever
- PRD defines Phase 1 scope → agents do not work Phase 2 issues in a Phase 1 sprint
- Design Doc defines module boundaries → `ingestion` does not import from `feature_generation`
- Working Agreement says "ask before adding dependencies" → CLAUDE.md does not override this

---

## 3. Definition of Ready

An issue is **Ready** when ALL of the following are true.
An issue that is not Ready must not be moved to In Progress.
Use `bash scripts/refine_issue.sh <N>` to walk through this checklist interactively.

```
[ ] Clear, single-sentence goal stating what "done" looks like
[ ] At least 3 specific, testable acceptance criteria
[ ] Milestone assigned (Phase 1 / 2 / 3 / 4 / Audit & Quality)
[ ] Labels set: type:* AND (phase:* or audit) — both required
[ ] No "blocked" label on the issue
[ ] Depends-on issues are closed, or explicitly noted as unblocked with justification in the issue body
[ ] Reviewed and approved for this sprint by the human lead
```

Signal for Ready: `needs-review` label removed (via `refine_issue.sh`). Absence of `blocked` = eligible.

---

## 4. Definition of Done

A task is **Done** when ALL of the following are true. This is the merge gate.
A task is not done when the code works — it is done when all criteria below are met.

### Functional
```
[ ] All acceptance criteria checkboxes in the GitHub Issue are checked
[ ] No unresolved TODO comments added during implementation
    (any TODOs must reference a new tracking issue with a number)
[ ] Behavior matches what the issue acceptance criteria describes
    (not what seemed like a good idea during implementation)
```

### Quality
```
[ ] bash scripts/local_check.sh exits 0 (ruff + black + mypy + import scan — all 4 stages)
[ ] pytest tests/ -m "not integration" passes with no new failures
[ ] pytest tests/ -m integration passes (required if PR touches DB writes or external API)
[ ] python .github/scripts/check_runtime_imports.py exits 0 (no langchain.* in src/)
[ ] All new public functions have: type hints on all parameters and return value, docstring
[ ] No xfail stubs converted to real passing tests unless the stub's issue is closed
[ ] No new xfail stubs added without a linked GitHub issue and comment explaining why
```

### Process
```
[ ] PR description complete: What Changed, What Agent Did, What Was Manually Reviewed
[ ] Every changed line reviewed as a second developer would review it
[ ] CI green on all stages (lint, type check, unit tests, runtime import scan)
[ ] Issue closed with comment: "Closing: all AC verified, merged in PR #N"
[ ] Branch deleted after merge
[ ] HEARTBEAT.md sprint issue row updated to "Done"
[ ] SESSION.md key decisions promoted to HEARTBEAT.md (before final session commit)
```

---

## 5. How Decisions Are Documented

| Decision Type | Where to Record |
|---------------|----------------|
| Implementation detail (within issue scope) | PR description + inline comment if non-obvious |
| Design choice that affects a module's structure | Issue comment + PR description body |
| Architecture decision (new module, schema change, module boundary) | `docs/adr/` (create directory when first needed) |
| Session-level choices | `SESSION.md` → key decisions promoted to `HEARTBEAT.md` |
| Sprint-level direction change | `HEARTBEAT.md` sprint notes + human approval required before proceeding |

---

## 6. Escalation Rules

Before proceeding, agents **must ask the human** when any of the following apply.
State what you're about to do, why you think it's necessary, and what the alternative is. Then wait.

| Trigger | Why It Requires Escalation |
|---------|---------------------------|
| Adding any package to `requirements.txt` or `requirements-dev.txt` | Changes production or CI dependencies for all contributors |
| Changing a public function signature used by multiple modules | May silently break callers outside current issue scope |
| Opening a PR to `main` (not `develop`) | Human reviews and merges all main-targeting PRs |
| Working on an issue outside the current sprint milestone | Scope creep requires explicit approval |
| Deviating from any ESOD constraint | ESOD is non-negotiable without human override |
| Closing an issue with unchecked acceptance criteria | Only human can accept partial delivery |
| Modifying CI/CD workflow files (`.github/workflows/`) | Changes quality gates for all contributors |
| Creating, modifying, or running database migrations | Schema changes have production impact |
| Any git operation that rewrites or deletes history | Irreversible |
| Implementing something not specified in the issue | Even if it seems like an obvious improvement |

---

## 7. Code Review Standards

Every changed line is reviewed as if a second developer wrote it.
Agent-generated code receives *more* scrutiny, not less, because agents can generate
plausible-looking code that has subtle bugs.

**Review checklist (all PRs):**
- **Correctness:** does it actually do what the acceptance criteria requested?
- **Edge cases:** what happens with `None`, empty list, zero, negative values, API timeout, DB unavailable?
- **Type annotations:** do they match actual runtime types? Are Optional types handled?
- **ESOD compliance:** no `langchain.*`, Pydantic at boundaries, tenacity on API calls, TIMESTAMPTZ in schema
- **Test quality:** do tests actually test behavior, or do they just pass trivially?
- **Import health:** no circular imports, no downstream agent imports
- **Naming:** clear, consistent with existing module conventions

---

## 8. The "No Surprise" Rule

For any change that generates **more than 100 lines of new code**:

1. State what you are about to implement (files, functions, approach)
2. List the files that will be created or modified
3. Confirm the approach is consistent with the Design Doc and ESOD
4. Wait for acknowledgment ("go ahead", "ok", or similar) before writing the first line of code

This rule exists because large agent sessions are difficult to steer after they start.
10 minutes of alignment before implementation prevents hours of rework.

---

## 9. What Agents May Never Do Without Human Approval

These are **absolute**. If you find yourself at one of these boundaries, stop, document
what you were about to do and why, and wait for the human to decide.

```
NEVER  add packages to requirements.txt or requirements-dev.txt — without approval
NEVER  merge to main or develop — open the PR; the human merges
NEVER  close issues with unchecked acceptance criteria — even one unchecked item = not done
NEVER  import from langchain.* or langgraph.* in src/ — zero tolerance, CI-enforced
NEVER  git push --force or git push --force-with-lease to main or develop
NEVER  git commit --no-verify — no hook bypass, ever
NEVER  change a public function signature outside the explicit scope of the issue
NEVER  create, modify, or run database schema migrations without human review
NEVER  work on issues outside the current sprint milestone without explicit approval
NEVER  silently skip a failing test or acceptance criterion — document and escalate instead
```
