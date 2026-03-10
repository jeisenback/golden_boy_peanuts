# Prompt Template: Refactor / Cleanup

**When to use:** Improving code structure, reducing duplication, or improving readability
WITHOUT changing any behavior.

**CRITICAL RULE:** Zero behavioral changes. The test suite must pass without modification.
If tests need to change, this is no longer a refactor — it is a bug fix or feature.

**Reference:** ADLC Section 5.5

---

## Copy this prompt into your Claude Code session:

---

You are refactoring existing code in the Energy Options Opportunity Agent.

GITHUB ISSUE: #[ISSUE_NUMBER] — [ISSUE_TITLE]

TARGET FILE(S):
- src/[path/to/file.py]
- [additional files if applicable]

REFACTOR GOAL:
[Describe specifically what is being improved. Be precise.
Examples:
  - Extract duplicated tenacity retry decorator into a shared utility in src/core/
  - Simplify a function that has more than 3 responsibilities into focused helpers
  - Reduce duplication between db.py files across agent modules
  - Improve naming of variables that use single-letter or ambiguous names]

CONSTRAINTS (strict):
- Zero behavioral changes. The existing test suite must pass without modification.
- Do not add new features or fix bugs as part of this refactor.
- Do not change public function signatures unless explicitly stated above.
- No new external dependencies.
- No langchain.* or langgraph.* imports.
- Do not move files or rename modules without explicit instruction.

DONE WHEN:
- All existing tests pass without any modification.
- The refactored code is measurably simpler than the original
  (fewer lines, clearer naming, or reduced duplication).
- A brief comment explains what was simplified and why.
- ruff and mypy pass.

Read the file(s). Propose the refactor approach in a brief description before implementing.
Wait for confirmation before writing any code.

---

## Variable Checklist Before Pasting

- [ ] `[ISSUE_NUMBER]` replaced
- [ ] `[ISSUE_TITLE]` replaced
- [ ] TARGET FILE(S) filled in
- [ ] REFACTOR GOAL is specific and measurable (not "clean up the code")
- [ ] Existing test suite confirmed passing locally before opening session
