# HEARTBEAT.md — Energy Options Opportunity Agent
# -----------------------------------------------------------------------
# COMMITTED. Always current. If this file is stale, it is wrong.
#
# Claude Code: READ THIS FILE BEFORE DOING ANYTHING ELSE EACH SESSION.
# It tells you what sprint is active, what you are working on, and
# what branch to use. If you skip this step, you will work on the wrong thing.
#
# Update protocol: see bottom of this file.
# -----------------------------------------------------------------------

## Current Sprint

| Field | Value |
|-------|-------|
| Sprint Number | 1 |
| Sprint Name | Sprint 1 — Repo & Agent Readiness |
| Goal | GitHub repo protected; agents can work reliably on scaffold; tooling gates enforced; Docker running |
| Start Date | 2026-03-10 |
| Target Close | 2026-03-17 |
| Status | ACTIVE |

## Sprint Issues

| # | Title | Status | Branch | Notes |
|---|-------|--------|--------|-------|
| 1 | Initialize GitHub repository: labels, milestones, branch protection | Not Started | — | HUMAN task — must close first; gates all branch work |
| 2 | Docker Compose for Postgres, venv, .env setup | Not Started | — | After #1 |
| 26 | Fix ingestion_agent.py: fetch_options_chain stub, orphaned import, logging | Not Started | — | After #1 |
| 27 | Add src/pipeline.py stub with run_pipeline() call sequence | Not Started | — | After #1 |
| 28 | Specify event_id generation in classify_event() docstring | Not Started | — | HUMAN decides strategy first, then agent |
| 29 | Add tests/conftest.py with shared Pydantic model fixtures | Not Started | — | After #1 |
| 30 | Add pytest to local_check.sh quality gate | Not Started | — | After #1 |
| 31 | Make post_session.sh active — invoke local_check.sh + git diff --stat | Not Started | — | After #1 |
| 32 | Add ADLC startup step to CLAUDE.md session startup sequence | Not Started | — | After #1 |
| 33 | Document non-interactive branch creation fallback in CLAUDE.md | Not Started | — | After #1 |

## Current Active Branch

`develop` — no active feature branch yet; create branches per issue via `bash scripts/new_branch.sh`

## Blockers

- None

## Last Merged PR

- None yet this sprint

---


## Sprint 0 Retro Notes

| | |
|---|---|
| What went well | Initial scaffold committed cleanly with CI workflows, agent stubs, Pydantic models, 25 GitHub issues across 5 milestones. All project management scaffolding (CLAUDE.md, sprint scripts, audit playbook) complete. |
| What was slow | — |
| What to change | — |

---

## Next Sprint Preview

**Sprint 1 — Phase 0: Project Setup**

Candidate issues (Phase 0 milestone):
- #1 Initialize GitHub repository: labels, milestones, branch protection
- #2 Local development environment: Docker Compose for Postgres
- #3 Refactor: extract shared get_engine() to src/core/db.py (DRY)
- #4 Refactor: extract shared tenacity retry config to src/core/retry.py (DRY)
- #5 CI pipeline verification: confirm all 4 workflows run green

Run `gh issue list --milestone "Phase 0: Project Setup"` to see full list.
Run `bash scripts/sprint_start.sh` to formally begin the sprint.

---

## HEARTBEAT Update Protocol

**Human updates HEARTBEAT at:**
- Sprint start: run `bash scripts/sprint_start.sh` (script writes sprint header block)
- Sprint close: run `bash scripts/sprint_close.sh` (script appends retro + summary)
- Any scope change, new blocker, or milestone shift mid-sprint

**Claude updates HEARTBEAT at:**
- Session end: promote Key Decisions from SESSION.md into sprint notes
- When an issue changes status (e.g., Not Started → In Progress → In Review)
- When a blocker is discovered or resolved
- Commit format: `chore: update HEARTBEAT after session YYYY-MM-DD (#issue)`

**HEARTBEAT is stale if:**
- The "Current Active Branch" does not match what `git branch --show-current` shows
- Sprint issues have changed status but the table has not been updated
- The last session was >24 hours ago and sprint notes have no new entries
- Status still says "PLANNING" after sprint_start.sh was run
