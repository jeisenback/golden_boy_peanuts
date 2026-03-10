# Prompt Template: Test Coverage

**When to use:** Adding tests to a module that lacks coverage, or building a golden dataset validation.

**Reference:** ADLC Section 5.4

---

## Copy this prompt into your Claude Code session:

---

You are writing tests for an existing module in the Energy Options Opportunity Agent.

GITHUB ISSUE: #[ISSUE_NUMBER] — [ISSUE_TITLE]

TARGET MODULE: src/agents/[module_name]/[file_name].py

TEST FILE: tests/agents/[module_name]/test_[file_name].py

COVERAGE GOAL:
[List the specific functions or behaviors that need test coverage — one per line]
- [ ] `function_name_1` — describe what should be tested
- [ ] `function_name_2`

TEST TYPES REQUIRED:
- Unit tests: test each function in isolation with mocked dependencies
- Integration tests: test the full module path using a real Postgres instance
  (use: from testcontainers.postgres import PostgresContainer)
[Add golden dataset test if this module produces edge_score or strategy candidate output]

GOLDEN DATASET (if applicable):
[Describe the known-good input scenario and expected output.
Example:
  Input: USO price = $X, realized vol = Y%, implied vol = Z%, no supply events
  Expected: edge_score for long_straddle in [0.40, 0.55]
  This scenario is documented in: [link or file reference]]

CONSTRAINTS:
- Do not mock the database in integration tests. Use testcontainers.
- Do not modify source code to make tests pass — tests must reflect real behavior.
- Use pytest fixtures for all shared setup (DB connection, sample data, etc.).
- Each test must have a clear docstring explaining exactly what it validates.
- No langchain.* or langgraph.* imports anywhere in test files.

Read the module first. Then write tests that would catch real failures.

---

## Variable Checklist Before Pasting

- [ ] `[ISSUE_NUMBER]` replaced
- [ ] `[module_name]` and `[file_name]` replaced
- [ ] COVERAGE GOAL list populated
- [ ] Golden dataset section filled in if output-facing, or deleted if not applicable
