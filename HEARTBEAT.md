# HEARTBEAT.md — Energy Options Opportunity Agent
# -----------------------------------------------------------------------
# COMMITTED. Append-only sprint notes. If this file is stale, it is wrong.
#
# Claude Code: READ THE REMOTE VERSION — never your local copy without fetching first:
#   git fetch origin develop --quiet
#   git show origin/develop:HEARTBEAT.md
# Your local branch may be hours behind. Always read from origin/develop.
#
# The Sprint Issues table shows sprint scope and final merged/closed state only.
# Live status (In Progress / In Review) is tracked on the GitHub issue via
# assignee + labels — NOT in this table. To check live status:
#   gh issue view <N>
#
# Update protocol: see bottom of this file.
# -----------------------------------------------------------------------

## Current Sprint

| Field | Value |
|-------|-------|
| Sprint Number | 2 |
| Sprint Name | Sprint 2 — Core Infrastructure |
| Goal | Shared db/retry core modules extracted; CI green; Phase 1 DB schema applied and verified |
| Start Date | 2026-03-12 |
| Target Close | 2026-03-19 |
| Status | ACTIVE |

## Sprint Issues

| # | Title | Status | Branch | Notes |
|---|-------|--------|--------|-------|
| 3 | Refactor: extract shared get_engine() to src/core/db.py | Merged | `refactor/3-extract-get-engine` | PR #54 merged |
| 4 | Refactor: extract shared tenacity retry config to src/core/retry.py | In Review | `refactor/4-extract-retry-config` | PR #55 open |
| 5 | CI pipeline verification: confirm all 4 workflows run green | Closed | `chore/5-ci-verification` | All 4 workflows verified green; issue closed |
| 6 | PostgreSQL schema: market_prices and options_chain tables | In Review | `feature/6-schema-market-prices` | PR open; schema verified with psql |
| 7 | PostgreSQL schema: feature_sets and strategy_candidates tables | Not Started | — | — |
| 34 | Replace remaining inline @retry decorators with @with_retry() | Not Started | — | Blocked until PR #55 merges |

## Issue Status: GitHub Is Authoritative

The Sprint Issues table above shows sprint scope and the final merged/closed state of each
issue. It is **not** updated by agents during a sprint.

To see live status for any issue:
```
gh issue view <N>                                             # assignee = who has claimed it
gh issue list --milestone "Sprint 2 — Core Infrastructure" --state open  # full sprint view
```

An issue is **claimed** when it has an assignee (`gh issue assign <N> --self`).
The `in-progress` label means actively being worked. The `needs-review` label means PR is open.
These transitions happen on the GitHub issue — not in this file.

The Sprint Issues table is updated only by:
- `bash scripts/sprint_start.sh` — writes the initial table at sprint start
- `bash scripts/sprint_close.sh` — updates final Merged/Closed rows at sprint end
- Human lead (manual corrections only)

---

## Current Active Branch

`feature/6-schema-market-prices`

## Blockers

- None currently. Issue #34 is sequentially dependent on PR #55 merge.

## Sprint Notes (2026-03-12)

Sprint 2 kicked off. Issues #3, #4, #5, #6 completed in single session:

- `#3` — `src/core/db.py` created with canonical `get_engine()`; all 4 agent `db.py` files updated to re-export via `# noqa: F401`. PR #54 merged.
- `#4` — `src/core/retry.py` created with `with_retry()` decorator factory; TypeVar-typed, `before_sleep_log` WARNING logging, env-configurable retries. Both agent files updated. PR #55 open.
- `#5` — CI verification: all 4 workflows (ci.yml, runtime-check.yml, integration.yml, security.yml) confirmed green against PR #54/#55. No code changes needed. Issue closed.
- `#6` — `db/schema.sql` created: `market_prices` and `options_chain` DDL with TIMESTAMPTZ columns, composite indexes, TimescaleDB hypertable migration comments (PRD §6.2). Applied to local Postgres (timescale/timescaledb:2.15.2-pg15) and verified with `\d`. PR open.

Decision: `db/schema.sql` uses `IF NOT EXISTS` guards throughout — idempotent, safe to re-run.

## Sprint Notes (2026-03-12, session 2)

Issue #5 closed: all 4 GitHub Actions workflows verified green against existing run history. No code changes required.
- `ci.yml` — push to develop run 22946745279 ✓; PR run 22927190645 ✓
- `runtime-check.yml` — push to develop run 22946745272 ✓; PR run 22927190654 ✓
- `integration.yml` — PR runs 23026165853, 23027379749 ✓ (exit code 5: 0 tests collected; acceptable per issue notes)
- `security.yml` — PR runs 23026165882, 23027379759 ✓ (no HIGH bandit findings; pip-audit clean)

## Sprint Notes (2026-03-12)

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
- Session end: APPEND a new dated Sprint Notes block — `## Sprint Notes (YYYY-MM-DD, session N)`
  containing: completed work, key decisions, blockers discovered or resolved
- When a PR is opened: append one line `- #N In Review, PR #M opened YYYY-MM-DD`
- **NEVER edit existing Sprint Notes blocks** — only add new blocks at the bottom
- **NEVER edit the Sprint Issues table rows** — use GitHub issue labels/assignee for status instead
- Commit format: `chore: update HEARTBEAT after session YYYY-MM-DD (#issue)`

**Claude does NOT update HEARTBEAT at:**
- Issue pickup — use `gh issue assign <N> --self` + apply `in-progress` label on GitHub instead
- Mid-sprint status transitions — update GitHub labels instead; HEARTBEAT is not the status store

**Sprint notes are append-only (makes HEARTBEAT merge-safe):**
Each session writes a unique dated block. Two agents writing notes in the same sprint produce
two independent blocks at the bottom of the file — git merges them as clean appends with no conflict.

**HEARTBEAT is stale if:**
- The "Current Active Branch" does not match what `git branch --show-current` shows
- Sprint issues have changed status but the table has not been updated
- The last session was >24 hours ago and sprint notes have no new entries
- Status still says "PLANNING" after sprint_start.sh was run
