---
name: Quality Sprint
about: Scheduled quality audit — coverage gaps, tech debt, xfail ratio, ruff/mypy violations
title: "[QUALITY SPRINT] "
labels: "type: test"
assignees: ""
---

## Trigger

<!-- What caused this quality sprint? Check one: -->
- [ ] Test coverage dropped below 80% for one or more modules
- [ ] 3+ consecutive feature sprints without a quality checkpoint
- [ ] Pre-Phase UAT milestone (UAT requires quality gate first)
- [ ] xfail count is not decreasing sprint-over-sprint
- [ ] Human lead decision

## Coverage Gaps

<!-- From `pytest --cov=src/ --cov-report=term-missing -m "not integration"` -->
<!-- (also available in audit-report-YYYY-MM-DD.txt from scripts/audit_sprint.sh) -->

| Module | Current Coverage | Target | Gap |
|--------|-----------------|--------|-----|
| `src/agents/ingestion/` | | 80% | |
| `src/agents/event_detection/` | | 80% | |
| `src/agents/feature_generation/` | | 80% | |
| `src/agents/strategy_evaluation/` | | 80% | |
| `src/core/` | | 80% | |

## Tech Debt Items

<!-- List TODO comments older than 2 sprints without a tracking issue,
     and patterns needing cleanup. Each TODO should be `# TODO (#N)` with issue ref. -->
- [ ] <!-- File:line — description — how old -->
- [ ] <!-- File:line — description — how old -->

## xfail Ratio

<!-- From `pytest tests/ -v --tb=no | grep -c XFAIL` -->
- **Current xfail count:** <!-- N -->
- **Total tests:** <!-- N -->
- **xfail ratio:** <!-- N/N = X% -->
- [ ] xfail ratio is lower than at the start of this quality sprint (trending down)
- [ ] Each remaining xfail either has a linked open issue or a documented justification in the test

## ruff Violations

<!-- From `ruff check src/ --statistics` -->
- [ ] No single violation type has more than 5 occurrences
- [ ] Violation statistics (paste `--statistics` output here):
  ```
  <!-- ruff statistics output -->
  ```

## mypy Errors

<!-- From `mypy src/ --strict` -->
- [ ] `mypy src/ --strict` exits 0 — no errors
- [ ] Any errors found: <!-- paste mypy output or "None" -->

## Test Isolation

<!-- Optional but recommended: -->
- [ ] Tests pass when run in random order (`pytest tests/ --randomly`) — or pytest-randomly not installed
- [ ] No test depends on global state mutated by another test

## Acceptance Criteria

- [ ] All modules in the Coverage Gaps table reach ≥80%, or have a new test issue opened for each gap
- [ ] xfail ratio is lower at the end of this sprint than at the start (or all remaining xfails are justified)
- [ ] No ruff violation type with more than 5 occurrences
- [ ] `mypy src/ --strict` exits 0
- [ ] All tech debt items listed above either resolved or have a new tracking issue `# TODO (#N)`
- [ ] `bash scripts/audit_sprint.sh` run; quality section reviewed; report saved
- [ ] Coverage improvement visible: before/after numbers documented in a comment on this issue
