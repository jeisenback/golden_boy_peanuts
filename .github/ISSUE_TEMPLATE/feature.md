---
name: Feature
about: New capability, agent, signal, data source, or strategy structure
title: "[FEATURE] "
labels: "type: feature"
assignees: ""
---

## Goal

<!-- One sentence: what this issue accomplishes. -->

## Context

<!-- Why this is needed. Link to PRD section or ESOD decision if relevant. -->
<!-- Example: PRD Section 4.1 — Data Ingestion & Normalization -->

## Acceptance Criteria

- [ ] <!-- Criterion 1 -->
- [ ] <!-- Criterion 2 -->
- [ ] All new public functions have type hints and docstrings
- [ ] Unit tests written and passing
- [ ] Integration test written and passing (if touching src/ pipeline)
- [ ] Runtime import scan passes (no langchain.* or langgraph.* in src/)
- [ ] ruff and mypy pass locally

## Agent Notes

<!-- If agent-assisted: which tool (Claude Code / Cursor / Copilot), what prompt template was used -->
<!-- Reference: docs/prompts/new_agent_module.md or docs/prompts/feature_existing_module.md -->

## Phase

<!-- Delete as appropriate -->
- [ ] Phase 1 — Core Market Signals & Options
- [ ] Phase 2 — Supply & Event Augmentation
- [ ] Phase 3 — Alternative / Contextual Signals
- [ ] Phase 4 — Optional Enhancements
