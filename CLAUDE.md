# CLAUDE.md — Energy Options Opportunity Agent

> **READ `HEARTBEAT.md` BEFORE DOING ANYTHING ELSE.**
> It tells you which sprint is active, what issue you are working, and what branch to use.
> If you skip this step, you will work on the wrong thing.

---

## Project Context

The Energy Options Opportunity Agent identifies options trading opportunities driven by
oil market instability. It ingests crude prices, options chains, and supply/news signals
to produce ranked candidate strategies (long straddles, call/put spreads) with composite
edge scores across WTI, Brent, USO, XLE, XOM, and CVX.

The system is a 4-agent pipeline (Ingestion → Event Detection → Feature Generation →
Strategy Evaluation) built in Python 3.11+, PostgreSQL, and **zero runtime LangChain
dependencies**. It is developed by a small team of AI agents + 1 human lead.
Phases: Phase 1 (core signals) → Phase 2 (supply/event) → Phase 3 (alternative signals) → Phase 4 (optional).

---

## Session Startup (Do This Every Time — In Order)

```
1. Read HEARTBEAT.md       → find active sprint, active branch, blockers, current issue
2. gh issue view <N>       → read ALL acceptance criteria for the issue you are working
3. Read SESSION.md         → if it exists from a prior session, absorb its context
4. Read docs/energy_options_adlc.md → select track (§2 Standard or §2b Lightweight), select prompt template (§5.1–§5.5), confirm DoD (§6)
     §2b Lightweight (small changes) · §5.1 New Agent Module · §5.2 Feature · §5.3 Bug Fix · §5.4 Test Coverage · §5.5 Refactor
5. git status              → confirm branch, confirm clean state
6. pytest -m "not integration"  → must pass before writing any code
```

If `SESSION.md` does not exist: `cp SESSION.md.template SESSION.md`, then fill in Session Goal.

**If HEARTBEAT.md says Status = PLANNING:** no sprint is active. Do not start work.
Run `bash scripts/sprint_start.sh` to begin a sprint, or ask the human lead what to work on.

---

## Your Role — Moderate Autonomy

You implement within the scope of a clearly defined issue. You explain before large changes.
You ask when uncertain about architecture, dependencies, or scope.

**Human lead owns:** architecture decisions, merging PRs, adding dependencies, sprint boundaries,
scope changes, issue closure with unchecked AC items, any irreversible operation.

**You own:** implementation within the issue, tests for your own code, code quality,
doc updates in scope, commit authorship, HEARTBEAT.md session updates.

For small, contained changes (docs, config, single-file private fixes with no interface
change), use the **Lightweight Track** defined in ADLC §2b instead of the full 10-step
loop. When uncertain which track applies, use the Standard Track.

---

## Decision Authority

| Area | You Decide | Must Ask Human |
|------|-----------|----------------|
| Implementation approach | Algorithm, data structure, function decomposition | Change to a public function signature |
| Testing | Write new tests, fix broken unit tests | Modify a regression test that exists for a bug fix |
| Code structure | Refactor within a file, rename private functions | Add or remove a module from `src/` |
| Imports | Use packages already in `requirements.txt` | Add any new package (even dev-only) |
| Database | Write parameterized SQL selects and inserts | Change schema, add/modify migrations |
| Documentation | Update in-scope `.md` files and docstrings | Modify ESOD, PRD, Design Doc, or SDLC |
| Commits | Author commit messages in correct format | — |
| Branch work | Work within the current issue's branch | Open a branch for a different issue |
| Error handling | `try/except` with logging | Swallow exceptions silently |
| HEARTBEAT.md | Update sprint notes and issue status at session end | Change sprint goal, milestone, or scope |
| SESSION.md | Create, update, and maintain throughout session | — |

**When in doubt:** explain what you're about to do and ask. Waiting costs less than rework.

---

## Before-You-Code Checklist

Before writing or editing any source file:

```
[ ] HEARTBEAT.md read → sprint is ACTIVE; issue confirmed in sprint table
[ ] Issue read completely → you can list all acceptance criteria from memory
[ ] Test suite passes locally: pytest tests/ -m "not integration"
[ ] Branch name follows convention; branch exists and is clean
[ ] SESSION.md is open and Goal section is filled in
[ ] You have READ any file you are about to edit (never modify a file you haven't read)
```

---

## Git Rules

Full reference: `docs/git_workflow.md`

**Quick rules:**

| Rule | Value |
|------|-------|
| Branch base | Always from `develop` — never from `main` |
| Branch format | `<type>/<issue>-<slug>` (e.g. `feature/8-fetch-crude-prices`) |
| Create branch | `bash scripts/new_branch.sh` (interactive — see note below) |
| Commit format | `<type>(<scope>): <description> (#<issue>)` |
| Issue ref required | Yes — every commit, no exceptions |
| Pre-PR gate | `bash scripts/local_check.sh` must exit 0 |
| Merge to develop | Squash and Merge |
| Merge to main | Merge Commit (human only) |

> **Non-interactive branch creation (agent / CI context):**
> `scripts/new_branch.sh` prompts for input and will hang in a non-interactive
> shell. When running as an agent (Claude Code, Cursor, CI), create the branch
> directly:
> ```
> git checkout -b <type>/<issue>-<slug> develop
> ```
> Example: `git checkout -b feature/8-fetch-crude-prices develop`

---

## Sprint Rules

Full reference: `docs/sprint_framework.md`

- Work **only** on issues in the current sprint milestone (see HEARTBEAT.md)
- **To pick up an issue:**
  1. Verify the issue is in the "Sprint Issues" table in HEARTBEAT.md with Status = Not Started or In Progress
  2. Verify issue meets Definition of Ready: `bash scripts/refine_issue.sh <N>`
  3. Create branch: `bash scripts/new_branch.sh` (or `git checkout -b <type>/<issue>-<slug> develop` if running non-interactively)
  4. Update HEARTBEAT issue table row: Status → "In Progress", Branch → your branch name
  5. Open (or update) `SESSION.md` with the issue goal
- **To refine a backlog issue:** `bash scripts/refine_issue.sh <N>` (pre-sprint only)
- **To start a sprint:** `bash scripts/sprint_start.sh` (human-led; requires develop branch)
- **Never work on out-of-sprint issues** without explicit human approval

---

## Issue and PR Lifecycle

| Stage | What You Do |
|-------|-------------|
| Issue enters sprint | Verify DoR, create branch, update HEARTBEAT row to "In Progress" |
| Working | Update SESSION.md each session; update HEARTBEAT when status changes |
| Ready for review | `bash scripts/local_check.sh` exits 0; open PR; add `needs-review` label; update HEARTBEAT to "In Review" |
| PR is open | Review every changed line as a second developer would; verify CI passes |
| Closing an issue | Add comment: `"Closing: all AC verified ✓, merged in PR #N"` — then close |
| Issue with unchecked AC | Do NOT close — escalate to human |

---

## Code Standards (ESOD Key Points)

Full ESOD: `docs/energy_options_esod.md`

```
NO langchain.* or langgraph.* in src/    ← CI-enforced; zero tolerance; no exceptions
ALL LLM calls via src/core/llm_wrapper.py ← never instantiate OpenAI/Anthropic SDK directly in agents
ALL external API calls use tenacity      ← @with_retry() from src/core/retry.py (once it exists)
ALL inbound data validated with Pydantic ← at every module boundary, before processing
TYPE HINTS on all public functions       ← params + return type; mypy strict; CI-enforced
POSTGRESQL only in src/                  ← DATABASE_URL from env; SQLite = tests only
TimescaleDB-compatible schema            ← TIMESTAMPTZ columns everywhere from day one
```

---

## Session End Protocol

Do this at the end of **every** session, before closing your terminal:

```
1. Commit all changes to current branch (no uncommitted work left behind)
2. bash scripts/local_check.sh → must exit 0 before your final commit
3. Update SESSION.md:
   - Mark completed items ✓
   - Describe in-progress state clearly (enough for a different agent to continue)
   - Fill in Handoff Notes
4. Promote Key Decisions from SESSION.md to HEARTBEAT.md sprint notes
5. Update HEARTBEAT sprint issues table: Status and Branch for your issue
6. Commit HEARTBEAT.md:
   git commit -m "chore: update HEARTBEAT after session YYYY-MM-DD (#issue)"
7. Push branch to remote:
   git push origin <your-branch>
8. If work is complete and all DoD criteria are met:
   - Open PR, add needs-review label, update HEARTBEAT to "In Review"
```

---

## Hard Stops

> These are absolute. If you reach one of these situations, stop.
> Write what you were about to do, why, and what the alternatives are.
> Do not proceed without explicit human approval.

```
NEVER  add packages to requirements.txt or requirements-dev.txt
NEVER  merge to main or develop (open the PR; the human merges)
NEVER  close issues with unchecked acceptance criteria items
NEVER  import from langchain.* or langgraph.* anywhere in src/
NEVER  git push --force or git push --force-with-lease to main or develop
NEVER  git commit --no-verify
NEVER  change a public function signature outside the explicit scope of the issue
NEVER  create, modify, or run database schema migrations without human review
NEVER  work on issues outside the current sprint milestone without explicit approval
NEVER  silently skip a failing test or acceptance criterion — document and escalate
```

---

## Reference Map

| What You Need | Where to Find It |
|---------------|-----------------|
| Sprint state, active branch, current issue | `HEARTBEAT.md` ← **read first** |
| Session context and handoff notes | `SESSION.md` |
| Branch naming, commit format, PR rules, forbidden ops | `docs/git_workflow.md` |
| Sprint DoR, DoD, ceremonies, Kanban, abort procedure | `docs/sprint_framework.md` |
| Team rules, document hierarchy, escalation | `docs/working_agreement.md` |
| Audit modes, triggers, checklists | `docs/audit_playbook.md` |
| Product scope, output schema, phases | `docs/energy_options_prd.md` |
| All technical constraints (non-negotiable) | `docs/energy_options_esod.md` |
| System architecture, data flow, module boundaries | `docs/energy_options_agent_design_doc.md` |
| 10-step ADLC loop, Claude Code prompt templates — **required reading before every implementation session** | `docs/energy_options_adlc.md` |
| Branching rules, CI pipeline, sprint cadence | `docs/energy_options_sdlc.md` |
| Pre-push quality gate | `bash scripts/local_check.sh` |
| Create a branch for an issue | `bash scripts/new_branch.sh` |
| Refine a backlog issue (DoR check) | `bash scripts/refine_issue.sh <N>` |
| Start a sprint | `bash scripts/sprint_start.sh` |
| Close a sprint | `bash scripts/sprint_close.sh` |
| Run an audit | `bash scripts/audit_sprint.sh` |
| Post-session hygiene checklist | `bash scripts/post_session.sh` |
