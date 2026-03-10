---
name: Test Coverage Gap
about: Missing unit, integration, or golden dataset test
title: "[TEST] "
labels: "type: test"
assignees: ""
---

## Goal

<!-- One sentence: which module or function currently lacks test coverage. -->

## Target Module

`src/agents/<module_name>/<file_name>.py`

## Coverage Gap

<!-- List the specific functions or behaviors that are untested: -->
- [ ] `function_name_1` — no unit test
- [ ] `function_name_2` — no integration test
- [ ] <!-- Golden dataset scenario missing (if output-facing) -->

## Test Types Required

- [ ] Unit tests (mocked dependencies, isolated function behavior)
- [ ] Integration tests (real Postgres via testcontainers — no mocked DB)
- [ ] Golden dataset test (if this module produces edge_score or candidate output)

## Golden Dataset Scenario (if applicable)

<!-- Describe the known-good input and expected output: -->
<!-- Example: Given X market state, the agent should produce edge_score ~0.47 for USO long_straddle -->

## Acceptance Criteria

- [ ] All targeted functions have pytest coverage
- [ ] Integration tests use testcontainers.postgres.PostgresContainer (not mocked DB)
- [ ] Each test has a docstring explaining what it validates
- [ ] Coverage report shows improvement vs. baseline
- [ ] No source code was modified to make tests pass

## Agent Notes

<!-- If agent-assisted: which tool, note that source code must NOT be modified -->
<!-- Reference: docs/prompts/test_coverage.md -->
