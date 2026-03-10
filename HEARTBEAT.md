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
| 1 | Initialize GitHub repository: labels, milestones, branch protection | Not Started | — | HUMAN task — must close first; gates all PR merges |
| 2 | Docker Compose for Postgres, venv, .env setup | In Review | `chore/2-docker-compose` | Ready for PR |
| 26 | Fix ingestion_agent.py: fetch_options_chain stub, orphaned import, logging | In Review | `fix/26-ingestion-scaffold` | Ready for PR |
| 27 | Add src/pipeline.py stub with run_pipeline() call sequence | In Review | `chore/27-pipeline-stub` | Ready for PR |
| 28 | Specify event_id generation in classify_event() docstring | Not Started | — | HUMAN decides strategy first — deterministic hash vs uuid4() |
| 29 | Add tests/conftest.py with shared Pydantic model fixtures | In Review | `test/29-conftest-fixtures` | Ready for PR |
| 30 | Add pytest to local_check.sh quality gate | In Review | `chore/30-pytest-local-check` | Ready for PR |
| 31 | Make post_session.sh active — invoke local_check.sh + git diff --stat | In Review | `chore/31-post-session-active` | Ready for PR |
| 32 | Add ADLC startup step to CLAUDE.md session startup sequence | In Review | `docs/32-adlc-startup-step` | Ready for PR |
| 33 | Document non-interactive branch creation fallback in CLAUDE.md | In Review | `docs/33-noninteractive-branch` | Ready for PR |

## Current Active Branch

All 8 agent-doable Sprint 1 branches committed. On `develop` between sessions.
Open PRs (human action required) after #1 (branch protection) is configured.

## Blockers

- **#1 (branch protection):** Human must configure GitHub repo settings (develop + main branch protection) before any Sprint 1 PR can merge. All 8 agent PRs are ready and waiting.
- **#28 (event_id strategy):** Human decision required — deterministic hash (SHA256 prefix of headline+source+timestamp[:8]) vs uuid4(). Deterministic = idempotent re-runs; uuid4 = simpler, requires DB-level dedup.

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
