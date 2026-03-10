---
name: Bug Fix
about: Incorrect behavior, bad output, or broken pipeline stage
title: "[BUG] "
labels: "type: fix"
assignees: ""
---

## Goal

<!-- One sentence: what behavior needs to be corrected. -->

## Bug Description

**Affected file:** `src/path/to/file.py`

**Expected behavior:**
<!-- What should happen -->

**Actual behavior:**
<!-- What actually happens -->

**Reproduction steps:**
<!-- Exact steps or inputs to reproduce -->

## Regression Test

<!-- REQUIRED: the regression test must be written BEFORE the fix is implemented. -->
<!-- Reference: docs/prompts/bug_fix.md (ADLC rule: write test first, then fix) -->

- [ ] Regression test written at `tests/path/test_file.py::test_function_name`
- [ ] Regression test currently FAILS (documenting pre-fix state)

## Acceptance Criteria

- [ ] Regression test passes after fix
- [ ] All pre-existing tests still pass
- [ ] Root cause documented in a comment near the fix
- [ ] No unrelated changes included
- [ ] ruff and mypy pass locally

## Agent Notes

<!-- If agent-assisted: which tool, note that regression test was written by human first per ADLC -->
<!-- Reference: docs/prompts/bug_fix.md -->
