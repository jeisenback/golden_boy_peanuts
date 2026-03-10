## What Changed

<!-- Describe the change in plain terms. One paragraph max.
     What does this PR add, fix, or remove? -->

## What the Agent Did

<!-- If this is agent-assisted work:
     - Which tool was used (Claude Code / Cursor / Copilot)?
     - What did the agent generate (file names, function stubs, tests, etc.)?
     - Were any agent-generated sections significantly revised?
     If fully human-written, write: "No agent tooling used in this PR." -->

## What Was Manually Reviewed

<!-- List the specific things you reviewed line-by-line as a human:
     - Logic correctness
     - Edge case handling
     - Type annotations verified
     - Import check passed locally
     - Tests verified to test real behavior, not mock behavior
     Example: "Reviewed all 3 new functions in ingestion_agent.py; confirmed tenacity
     retry parameters match ESOD standard; removed 2 leftover debug prints." -->

## Testing

- [ ] `pytest` run locally — all tests pass
- [ ] New tests added for this change
- [ ] Integration test included (if touching DB or external API)

## Quality Gates (run locally before PR)

- [ ] `ruff check src/ tests/` — passes
- [ ] `black --check src/ tests/` — passes
- [ ] `mypy src/` — passes (strict mode)
- [ ] `python .github/scripts/check_runtime_imports.py` — exits 0

## Related Issue

Closes #<!-- issue number -->

## Notes for Reviewer

<!-- Any unusual decisions, trade-offs, or items that need extra attention. -->
<!-- If touching DB schema: confirm TimescaleDB compatibility verified. -->
