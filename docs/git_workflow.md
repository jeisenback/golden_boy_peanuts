# Git Workflow — Energy Options Opportunity Agent
#
# Companion to: docs/energy_options_sdlc.md (Section 4)
# CLAUDE.md summary: see CLAUDE.md § Git Rules
# This document is the authoritative git reference. CLAUDE.md summarizes and points here.

## 1. Branch Naming

| Type | Pattern | Example | When to Use |
|------|---------|---------|-------------|
| `feature/` | `feature/<issue>-<slug>` | `feature/8-fetch-crude-prices` | New capability, agent, signal, data source |
| `fix/` | `fix/<issue>-<slug>` | `fix/18-negative-edge-score` | Bug or defect correction |
| `chore/` | `chore/<issue>-<slug>` | `chore/3-extract-get-engine` | Tooling, deps, docs, non-functional changes |
| `agent/` | `agent/<issue>-<slug>` | `agent/8-scaffold-ingestion` | Active Claude Code / Cursor / Copilot session |
| `refactor/` | `refactor/<issue>-<slug>` | `refactor/3-core-db-extraction` | Code restructure, zero behavioral change |

**Rules:**
- All branches from `develop`. Never from `main`. Never directly to `develop` or `main`.
- Slug: lowercase, hyphens only, no underscores, no spaces, no special characters.
- Issue number is **required** in the branch name. No issue = no branch.
- Use `bash scripts/new_branch.sh` for interactive creation (enforces these rules).

---

## 2. Commit Format

```
<type>(<scope>): <description> (#<issue>)
```

**Examples:**
```
feat(ingestion): add fetch_crude_prices via Alpha Vantage (#8)
fix(feature_gen): handle None implied_volatility in vol gap calc (#18)
chore(deps): pin tenacity==8.2.3 in requirements.txt (#21)
test(ingestion): add golden dataset integration test for USO edge score (#14)
refactor(core): extract get_engine to src/core/db.py (#3)
docs(adlc): update refactor prompt template section 5.5 (#9)
ci(security): add bandit HIGH threshold check (#25)
```

**Rules:**
- Issue reference `(#N)` is **required** on every commit. No exceptions.
- Description: imperative mood ("add", "fix", "extract" — not "added", "fixes"), no period.
- Total subject line: 72 characters max.
- Body (optional): explain *why*, not *what*. Blank line after subject.

---

## 3. Commit Types

| Type | When to Use |
|------|-------------|
| `feat` | New feature, signal, agent, data feed, or endpoint |
| `fix` | Bug fix or defect correction |
| `chore` | Deps, config, docs, tooling — no functional change |
| `test` | Adding or updating tests only (no source changes) |
| `refactor` | Code restructure with no behavioral change |
| `docs` | Documentation only — .md files, docstrings |
| `ci` | GitHub Actions workflows, scripts, CI/CD config |

---

## 4. PR Requirements Before Opening

Before `gh pr create` or clicking "Open pull request":

```
[ ] bash scripts/local_check.sh exits 0 (ruff + black + mypy + import scan — all 4 stages)
[ ] pytest tests/ -m "not integration" passes locally
[ ] pytest tests/ -m integration passes (if the PR touches DB writes or external API calls)
[ ] git diff reviewed line-by-line — every changed line, not just your additions
[ ] No debug prints, commented-out code, unused imports left in the diff
[ ] All new public functions have type hints and docstrings
[ ] SESSION.md key decisions promoted to HEARTBEAT.md
[ ] HEARTBEAT.md sprint issue row updated to "In Review"
```

---

## 5. PR Description Requirements

Every PR must fill out all sections of `.github/pull_request_template.md`:

- **What Changed:** plain English, one paragraph max, what the code does now that it didn't before
- **What the Agent Did:** which tool was used, what it generated, what was substantially revised by human
- **What Was Manually Reviewed:** specific files and functions reviewed line-by-line (be specific)
- **Testing:** pytest output excerpt, new tests added, integration tests if DB/API touched
- **Quality Gates:** all four checkboxes checked before opening (ruff, black, mypy, import scan)
- **Related Issue:** `Closes #N` — this auto-closes the issue when PR merges
- **Notes for Reviewer:** trade-offs made, DB schema changes, unusual patterns used and why

---

## 6. Merge Strategy

| Branch Target | Strategy | Why |
|---------------|----------|-----|
| `develop` | **Squash and Merge** | Collapses noisy agent micro-commits into a clean logical unit; keeps develop linear |
| `main` | **Merge Commit** | Preserves full develop branch history; provides audit trail for each release |

After merge: **delete the source branch immediately.** Never leave stale branches in the remote.

---

## 7. Closing Issues

Issues are closed **only** by:
1. **PR merge** with `Closes #N` in the PR description (GitHub auto-closes on merge)
2. **Manual close** with an explicit comment in the issue

**Manual close comment must include:**
```
Closing: all AC verified ✓, implemented in PR #[N], merged YYYY-MM-DD.
Tool used: [Claude Code / human / Cursor]
```

**Never:**
- Close an issue silently with no comment
- Close an issue with unchecked acceptance criteria items
- Close an issue before the PR is merged (pre-close is an error)

---

## 8. Forbidden Operations

These are **hard stops**. Claude must never perform these operations. If you find yourself needing one of these, stop, explain, and wait for human approval.

```bash
git push --force origin main          # destroys history permanently
git push --force origin develop       # destroys history permanently
git push --force-with-lease origin main    # still dangerous on main
git push --force-with-lease origin develop # still dangerous on develop
git commit --no-verify                # bypasses hooks; prohibited
git commit --amend                    # after pushing to remote (rewrites history)
git push origin main                  # direct push without PR
git push origin develop               # direct push without PR
git rebase -i origin/main             # interactive rebase on shared branches
git rebase -i origin/develop          # interactive rebase on shared branches
```

**Hotfix procedure** (the only path to main without a develop merge):
1. Branch `fix/<issue>-<slug>` from `main`
2. PR from fix branch → main (human reviews and merges)
3. Immediately cherry-pick or merge-forward to `develop`
4. Delete the fix branch

---

## 9. Tag Format

- Pattern: `vMAJOR.MINOR.PATCH` (semantic versioning)
- Applied **only on `main`**, **only after UAT sign-off** from the human lead
- **Annotated tags only:** `git tag -a v0.1.0 -m "Phase 1: Core Market Signals — UAT signed off"`
- Never tag `develop` or feature branches
- Phase mapping: Phase 1 = v0.1.0, Phase 2 = v0.2.0, Phase 3 = v0.3.0, Phase 4 = v0.4.0

---

## 10. Relationship to Existing SDLC Doc

`docs/energy_options_sdlc.md` Section 4 is the upstream source for branching conventions.
This document **extends** it with explicit commit format, forbidden operations, and issue closing protocol.
If there is a conflict, SDLC takes precedence; raise it as a documentation issue to reconcile.
