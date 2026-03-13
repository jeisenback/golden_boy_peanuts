# Sprint Framework — Energy Options Opportunity Agent
#
# Companion to: docs/energy_options_sdlc.md (Section 6)
# Scripts: scripts/sprint_start.sh, scripts/sprint_close.sh, scripts/refine_issue.sh
#
# The SDLC defines the system. The ADLC defines the task loop.
# This document defines what happens at sprint boundaries:
# how work enters, how sprints close, and what a healthy sprint looks like.

## 1. Sprint Length

**Recommended: 1 week (Monday → Friday)**

Rationale for AI-assisted development:
- AI agents generate 2–3x human coding velocity; weekly cadence prevents runaway scope
- 1-week retros preserve context better than bi-weekly; insights are fresh and actionable
- GitHub milestone due dates map cleanly to weekly calendar boundaries

Flexibility: sprint length may be 2 weeks for Phase transition sprints (e.g., Phase 1 → Phase 2
review + planning sprint). Document any deviation in HEARTBEAT.md.

---

## 2. Sprint Ceremonies

### 2.1 Sprint Planning (Start of Sprint)
- **Trigger:** Human decides sprint is starting
- **Tool:** `bash scripts/sprint_start.sh`
- **Inputs:** Sprint number, sprint goal (one sentence), milestone name
- **Output:** HEARTBEAT.md updated with sprint header and issue table; issues confirmed Ready
- **Async:** No meeting required. Entire ceremony happens via script + HEARTBEAT.md.
- **Time budget:** 30 minutes max

### 2.2 Sprint Entry Gate (Automated via sprint_start.sh)
See Section 5 — Sprint Entry Checklist.
The script enforces entry criteria; if any item fails, the sprint does not start.

### 2.3 Daily Check-in (Async — No Meeting)
- Not a standup. Async via HEARTBEAT.md + GitHub issue comments.
- At the **end of each session**, the agent:
  1. Updates GitHub issue labels to reflect current status (`in-progress`, `needs-review`)
  2. APPENDs a new dated Sprint Notes block to HEARTBEAT.md containing:
     - What was completed since the previous update
     - Key decisions made
     - Any new blockers discovered or resolved
  3. **NEVER edits the Sprint Issues table or existing Sprint Notes blocks**
- Human reviews HEARTBEAT.md at the start of each day
- Human responds to blockers in issue comments (agents check comments at session start)
- SESSION.md supplements HEARTBEAT for intra-session granularity

### 2.4 Sprint Review (End of Sprint)
- **Trigger:** Human decides sprint is closing
- **Tool:** `bash scripts/sprint_close.sh`
- **Output:** Open issues listed, retro captured, HEARTBEAT updated, next sprint previewed
- **Async:** No meeting required

### 2.5 Retrospective (Embedded in sprint_close.sh)
Three prompts, captured in HEARTBEAT.md:
1. What went well this sprint?
2. What was slow or blocked?
3. What will we change next sprint?

---

## 3. Definition of Ready

An issue is **Ready** when ALL of the following conditions are met.
An issue that is not Ready must not be moved to In Progress.

Use `bash scripts/refine_issue.sh <N>` to walk through this checklist interactively.

```
[ ] 1. Has a clear, single-sentence goal stating what "done" looks like
[ ] 2. Has at least 3 specific, testable acceptance criteria (checkboxes in issue body)
[ ] 3. Milestone assigned (Phase 0 / 1 / 2 / 3 / 4 / Audit & Quality)
[ ] 4. Labels set: type:* AND (phase:* or audit) — both required
[ ] 5. No "blocked" label on the issue
[ ] 6. Depends-on issues are closed, or explicitly noted as unblocked with justification
[ ] 7. Reviewed and approved for this sprint by the human lead
```

Signal for Ready: `needs-review` label removed (done by `refine_issue.sh` when all 7 pass).
Add `agent-assisted` label if Claude Code / Cursor / Copilot will lead implementation.

**Issue pickup sequence** (these run at claim time — not sprint planning):
1. `gh issue view <N>` — confirm the issue has no assignee; if assigned, pick a different issue
2. `gh issue assign <N> --self` — atomic claim; GitHub serializes concurrent requests
3. `gh issue edit <N> --add-label in-progress`
4. Create branch: `git checkout -b <type>/<issue>-<slug> develop`
No HEARTBEAT edit is required at pickup time. Status is tracked via GitHub assignee + labels.

---

## 4. Definition of Done

A task is Done when ALL criteria in `docs/working_agreement.md` § 4 are met.
See that document for the complete gate — it is the authoritative source.

Key gate items reproduced here for scanning:
- All acceptance criteria checkboxes checked in the issue
- `bash scripts/local_check.sh` exits 0
- CI green on all stages
- Issue closed with comment referencing PR number
- Branch deleted after merge
- HEARTBEAT.md sprint notes updated (append-only — new dated block added)

---

## 5. Sprint Entry Checklist

Run `bash scripts/sprint_start.sh` before any sprint work begins.
The script validates the following and exits 1 on any 'n':

```
[ ] 1. Current branch is `develop`
[ ] 2. Working directory is clean (git status shows no uncommitted changes)
[ ] 3. develop is current with origin/develop (not behind remote)
[ ] 4. Sprint number is provided (positive integer)
[ ] 5. Sprint goal is stated (non-empty sentence)
[ ] 6. Milestone name matches an existing GitHub milestone
[ ] 7. All sprint issues pass Definition of Ready (verified interactively)
[ ] 8. CI is currently green on develop (human confirms)
```

If any item is answered 'n': sprint does not start; script exits with message listing failures.
If all items pass: script writes sprint header + issue table to HEARTBEAT.md and prints confirmation.

---

## 6. Sprint Exit Checklist

Run `bash scripts/sprint_close.sh` at sprint end.
The script captures retro notes and writes to HEARTBEAT.md.

```
[ ] 1. All sprint issues are closed (warning if any remain — not a hard fail)
[ ] 2. CI is currently green on develop — HARD FAIL if 'n'
    "Do not close sprint until develop CI is green. Investigate the failure."
[ ] 3. HEARTBEAT.md has session notes from this sprint (human confirms)
[ ] 4. Carry-over issues identified and moved to next sprint backlog or marked blocked
[ ] 5. Retro notes captured (script prompts 3 questions — responses go to HEARTBEAT.md)
[ ] 6. PR to main opened or explicitly planned (if sprint completed Phase-milestone work)
```

Hard fail: CI not green → sprint cannot be closed until fixed.
Warning (non-fatal): open issues → noted as carry-overs in HEARTBEAT.md.

---

## 7. Kanban Column Definitions

| Column | Definition | GitHub Label / State |
|--------|-----------|---------------------|
| **Backlog** | Defined but not yet scheduled in a sprint | Open, no current sprint milestone |
| **Ready** | Meets DoR; scheduled for current sprint; not blocked | Open, current sprint milestone, no `blocked` label |
| **In Progress** | Actively being worked; a branch exists; issue is assigned | Open, `in-progress` label, assignee set via `gh issue assign <N> --self`, no open PR |
| **In Review** | PR open; awaiting human review | `needs-review` label applied; `in-progress` label removed |
| **Done** | All DoD criteria met; issue closed; branch deleted | Closed |

---

## 8. GitHub Projects Setup

**Board name:** `Energy Options — Sprint Board`

**Column automation:**
- Backlog → open issues without the current sprint milestone assigned
- Ready → issues in current sprint milestone, no `blocked` label, no open PR
- In Progress → issues with an open branch matching the issue number
- In Review → issues with `needs-review` label
- Done → closed issues

**One-time setup:**
1. Go to `https://github.com/jeisenback/golden_boy_peanuts/projects`
2. Create a new Board-type project: `Energy Options — Sprint Board`
3. Add the automation rules above for each column
4. Link the project to the repository

**All issues from `create_issues.sh` are already labeled and milestoned** — they will populate Backlog automatically once linked.

---

## 9. Sprint Naming Convention

Format: `Sprint N — [Milestone Name]: [Brief Goal]`

**Examples:**
```
Sprint 1  — Phase 0: Project Setup
Sprint 2  — Phase 1: Ingestion agent fetch functions
Sprint 3  — Phase 1: Feature generation and edge scoring
Sprint 4  — Audit & Quality: Pre-Phase 2 architecture review
Sprint 5  — Phase 2: EIA integration and event detection
```

**Rules:**
- Sprint number is global (never reset between phases or milestones)
- Milestone name must match an existing GitHub milestone exactly
- Brief goal: 2–6 words, plain English, no jargon

---

## 10. Emergency Sprint Abort Procedure

If a sprint must be aborted mid-sprint (critical blocker, scope invalidated, architectural rework needed):

1. **Human declares abort** verbally or via issue/HEARTBEAT comment
2. **Stop all agent work immediately** — do not continue on any in-progress issue
3. Commit all WIP to the current branch:
   `git commit -m "chore: sprint abort WIP — [reason] (#issue)"`
4. **Do not merge** any in-progress PRs to develop
5. Run `bash scripts/sprint_close.sh` with retro note: **"ABORTED: [reason]"**
6. Move incomplete issues back to Backlog or apply `blocked` label with explanation
7. Update HEARTBEAT.md:
   - Set Sprint Status to "ABORTED"
   - Document the abort reason
   - List which issues are carry-overs vs. invalidated
8. Human re-plans; run `bash scripts/sprint_start.sh` to begin the recovery sprint

**Sprint abort does not mean delete work.** All WIP branches stay.
The recovery sprint evaluates what is salvageable and rescopes accordingly.
