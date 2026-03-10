# Prompt Template: Bug Fix

**When to use:** Fixing a confirmed defect.

**CRITICAL ADLC RULE:** Write the regression test BEFORE opening Claude Code.
The human writes the failing test. Claude Code fixes the code. The test must NOT be modified.

**Reference:** ADLC Section 5.3

---

## Copy this prompt into your Claude Code session:

---

You are fixing a confirmed bug in the Energy Options Opportunity Agent.

GITHUB ISSUE: #[ISSUE_NUMBER] — [ISSUE_TITLE]

AFFECTED FILE: src/[path/to/file.py]

BUG DESCRIPTION:
[Describe exactly what is wrong.
  - What inputs trigger the bug
  - What the expected behavior is
  - What actually happens
  - Any error messages or tracebacks]

REPRODUCTION:
[Paste the exact command or inputs to reproduce, or the failing test output]

REGRESSION TEST:
The regression test has already been written by the human. It currently FAILS.
It is located at:
  tests/[path]/test_[name].py :: test_[function_name]

DO NOT modify the regression test. The production code must change to make the test pass.

CONSTRAINTS:
- Fix only the confirmed bug. Do not refactor surrounding code.
- Do not modify the regression test — the code must change, not the test.
- All existing tests must continue to pass after the fix.
- Document the root cause in a comment near the fix.
- Keep the fix minimal. Prefer the smallest correct change.
- No langchain.* or langgraph.* imports.

Read the affected file, understand the root cause, then implement the minimal fix.

---

## Variable Checklist Before Pasting

- [ ] Regression test already written and confirmed FAILING locally
- [ ] `[ISSUE_NUMBER]` replaced
- [ ] `[ISSUE_TITLE]` replaced
- [ ] `[path/to/file.py]` replaced
- [ ] BUG DESCRIPTION filled in with inputs, expected, and actual behavior
- [ ] REGRESSION TEST location filled in (`tests/...::test_...`)
