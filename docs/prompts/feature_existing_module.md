# Prompt Template: Feature Within an Existing Module

**When to use:** Adding a new capability, signal, or behavior to a module that already exists.

**Reference:** ADLC Section 5.2

---

## Copy this prompt into your Claude Code session:

---

You are adding a feature to an existing module in the Energy Options Opportunity Agent.

GITHUB ISSUE: #[ISSUE_NUMBER] — [ISSUE_TITLE]

TARGET MODULE: src/agents/[module_name]/[file_name].py

FEATURE:
[One sentence describing exactly what is being added]

ACCEPTANCE CRITERIA (from GitHub Issue):
- [ ] [Criterion 1 — paste directly from the issue]
- [ ] [Criterion 2]
- [ ] All new public functions have type hints and docstrings
- [ ] New tests added and passing

CONTEXT:
- Read the existing module before making any changes.
- The existing test suite must continue to pass after your changes.
- Add new tests in tests/agents/[module_name]/test_[module_name].py

CONSTRAINTS:
- Do not refactor existing code unless it directly blocks the feature.
- Do not add new dependencies without flagging them for human approval first.
- No langchain.* or langgraph.* imports.
- Type hints required on all new functions.
- All new external API calls must use tenacity for retry.
- Pydantic validation required if adding a new inbound data path.

EXPECTED OUTPUT:
[Describe the new function signature, return type, and behavior.
Example:
  def compute_supply_shock_probability(events: list[DetectedEvent]) -> float:
      ...  # returns value in [0.0, 1.0]
]

Read the module first. Then implement the feature. Then write the tests.

---

## Variable Checklist Before Pasting

- [ ] `[ISSUE_NUMBER]` replaced
- [ ] `[ISSUE_TITLE]` replaced
- [ ] `[module_name]` replaced
- [ ] `[file_name]` replaced
- [ ] FEATURE description filled in
- [ ] ACCEPTANCE CRITERIA populated from the GitHub Issue
- [ ] EXPECTED OUTPUT filled in with function signature if known
