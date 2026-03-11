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
| 1 | Initialize GitHub repository: labels, milestones, branch protection | Merged | `chore/1-codeowners` | PR #50 merged |
| 2 | Docker Compose for Postgres, venv, .env setup | Merged | `chore/2-docker-compose` | PR #36 merged |
| 26 | Fix ingestion_agent.py: fetch_options_chain stub, orphaned import, logging | Merged | `fix/26-ingestion-scaffold` | PR #51 merged |
| 27 | Add src/pipeline.py stub with run_pipeline() call sequence | Merged | `chore/27-pipeline-stub` | PR #38 merged |
| 28 | Specify event_id generation in classify_event() docstring | Merged | — | Closed — deterministic UUID5/SHA256 approach adopted |
| 29 | Add tests/conftest.py with shared Pydantic model fixtures | Merged | `test/29-conftest-fixtures` | PR #39 merged |
| 30 | Add pytest to local_check.sh quality gate | Merged | `chore/30-pytest-local-check` | PR #35 merged |
| 31 | Make post_session.sh active — invoke local_check.sh + git diff --stat | Merged | `chore/31-post-session-active` | PR #40 merged |
| 32 | Add ADLC startup step to CLAUDE.md session startup sequence | Merged | `docs/32-adlc-startup-step` | PR #41 merged |
| 33 | Document non-interactive branch creation fallback in CLAUDE.md | Merged | `docs/33-noninteractive-branch` | PR #42 merged |

## Current Active Branch

`develop` — all Sprint 1 issues merged and closed. Ready for human to run `bash scripts/sprint_close.sh`.

## Blockers

- None — all Sprint 1 blockers resolved.

## Sprint Notes (2026-03-11)

All Sprint 1 PRs confirmed merged. Issue table updated to reflect merged state. No open blockers. Sprint ready for human to close via `bash scripts/sprint_close.sh`. Next sprint candidates: #3, #4, #5, #6, #7, #8 (Phase 0 / Phase 1 infra).

## Sprint Notes (2026-03-10, session 2)

- `#26` follow-up: restores `write_option_records` import (with `# noqa: F401`) to satisfy AC item 3; PR #51 open for review

## Sprint Notes (2026-03-10)

All 8 agent-doable issues committed on separate branches in a single session:

- `#30` — pytest added as Stage 5 in local_check.sh
- `#31` — post_session.sh now active: executes git diff, import scan, local_check before checklist. Exits non-zero on failure.
- `#32` — ADLC step 6 added to CLAUDE.md Session Startup (read ADLC before coding)
- `#33` — Non-interactive branch creation fallback documented in CLAUDE.md Git Rules
- `#29` — tests/conftest.py added with 8 pytest fixtures across all 4 boundary models
- `#26` — ingestion_agent.py fixed: fetch_options_chain() stub added, module-level basicConfig() removed, OptionRecord import added
- `#27` — src/pipeline.py stub added documenting 4-agent call sequence; Phase 1 events=[] documented explicitly
- `#2`  — docker-compose.yml added (timescale/timescaledb:latest-pg16, port 5432, named volume, health check); README Quickstart updated

Key architecture observation documented: `run_event_detection()` takes no arguments (fetches own data from DB). This means Event Detection and Ingestion are currently decoupled at the function boundary — Phase 2 may need to revisit this.

## Last Merged PR

- PR #53 (develop ← develop merge), PR #52/#51 (#26 ingestion fix), PR #50 (#1 CODEOWNERS), PR #48 (#31 post_session), PR #45 (#27 pipeline), PR #42 (#33), PR #41 (#32), PR #40 (#31), PR #39 (#29), PR #38 (#27), PR #37 (#26), PR #36 (#2), PR #35 (#30) — all Sprint 1 PRs merged 2026-03-10

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
