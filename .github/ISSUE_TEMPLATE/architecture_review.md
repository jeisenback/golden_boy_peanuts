---
name: Architecture Review
about: Scheduled architecture audit — module boundaries, ESOD compliance, dependency review
title: "[ARCH REVIEW] "
labels: "type: chore"
assignees: ""
---

## Trigger

<!-- What caused this review? Check one: -->
- [ ] Pre-Phase transition (Phase ___ → Phase ___)
- [ ] New team member or AI agent tool added
- [ ] Quarterly baseline review
- [ ] Human lead decision

## Scope

<!-- Check all modules in scope for this review: -->
- [ ] `src/agents/ingestion/`
- [ ] `src/agents/event_detection/`
- [ ] `src/agents/feature_generation/`
- [ ] `src/agents/strategy_evaluation/`
- [ ] `src/core/`
- [ ] Other: <!-- specify -->

## Architecture Concerns

<!-- List specific concerns identified before or during the review.
     Example: "ingestion agent imports from feature_generation (boundary violation)" -->
- [ ] <!-- Concern 1 -->
- [ ] <!-- Concern 2 -->

## ESOD Compliance Items

<!-- From docs/energy_options_esod.md — verify each: -->
- [ ] No `langchain.*` or `langgraph.*` imports in `src/` — `python .github/scripts/check_runtime_imports.py` exits 0
- [ ] All LLM calls route through `src/core/llm_wrapper.py` (no direct SDK instantiation in agents)
- [ ] All external API calls use `tenacity` retry (no bare `requests.get` without decorator)
- [ ] All inbound data validated with `Pydantic` at module boundaries
- [ ] PostgreSQL only in non-test code (no SQLite in `src/agents/` or `src/core/`)

## Module Boundary Checks

<!-- Verify each cross-module import restriction: -->
- [ ] `ingestion` does not import from `feature_generation` or `strategy_evaluation`
- [ ] `event_detection` does not import from `feature_generation` or `strategy_evaluation`
- [ ] `feature_generation` does not import from `strategy_evaluation`
- [ ] No circular imports — verify: `python -c "import src.agents.ingestion"` (and each other agent)

## Dependency Review

<!-- For each package in requirements.txt: -->
- [ ] All packages in `requirements.txt` are actively used in `src/` (no unused deps)
- [ ] All packages have pinned or bounded versions

## Schema Review

<!-- TimescaleDB compatibility per PRD Section 6.1: -->
- [ ] All time-series tables use `TIMESTAMPTZ` columns (not `TIMESTAMP` or `DATETIME`)
- [ ] Schema supports future `SELECT create_hypertable('table', 'timestamp')` without SQL changes
- [ ] Migration path documented (or no schema changes this sprint)

## Acceptance Criteria

- [ ] All ESOD compliance items above are verified clean
- [ ] All module boundary checks confirmed — no violations (or violations have separate fix issues)
- [ ] Dependency review complete — no unused packages
- [ ] Schema review complete — all TIMESTAMPTZ, migration path noted if needed
- [ ] `bash scripts/audit_sprint.sh` run; architecture section reviewed; report saved
- [ ] Any violations found have separate GitHub issues opened with `type: fix` label
