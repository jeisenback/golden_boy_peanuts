# Pre-Landing Review Checklist — Energy Options Opportunity Agent

## Instructions

Review the `git diff origin/develop` output for the issues listed below. Be specific — cite `file:line` and suggest fixes. Skip anything that's fine. Only flag real problems.

**Three-pass review:**
- **Pass 0 (HARD RULES):** Energy Options architectural constraints. Any violation is a blocker — no exceptions, no PRs merged with these open.
- **Pass 1 (CRITICAL):** SQL & Data Safety, Race Conditions, LLM Trust Boundary, Enum Completeness.
- **Pass 2 (INFORMATIONAL):** All remaining categories.

All findings get action via Fix-First Review: obvious mechanical fixes are applied automatically,
genuinely ambiguous issues are batched into a single user question.

**Output format:**

```
Pre-Landing Review: N issues (X hard-rule violations, Y critical, Z informational)

**AUTO-FIXED:**
- [file:line] Problem → fix applied

**NEEDS INPUT:**
- [file:line] Problem description
  Recommended fix: suggested fix
```

If no issues found: `Pre-Landing Review: No issues found.`

Be terse. For each issue: one line describing the problem, one line with the fix. No preamble, no summaries, no "looks good overall."

---

## Pass 0 — HARD RULES (Energy Options)

These are CI-enforced constraints from the ESOD. Any violation is a BLOCKER. Treat as CRITICAL / ASK — never AUTO-FIX without user confirmation.

#### LangChain/LangGraph Ban
- Any `import langchain` or `from langchain` anywhere in `src/`
- Any `import langgraph` or `from langgraph` anywhere in `src/`
- Zero tolerance. No exceptions.

#### LLM Instantiation
- Any direct instantiation of OpenAI, Anthropic SDK, or other LLM clients outside `src/core/llm_wrapper.py`
- Pattern to flag: `from openai import`, `import anthropic`, `OpenAI()`, `Anthropic()` in any file other than `src/core/llm_wrapper.py`

#### External API Retry Policy
- Any external API call (HTTP, third-party SDK) that does NOT use `@with_retry()` from `src/core/retry.py`
- Flag: bare `requests.get()`, `requests.post()`, or external SDK calls without the retry decorator

#### Pydantic Validation at Boundaries
- Inbound data (from external APIs, DB queries returning raw dicts, agent-to-agent message passing) that is NOT validated through a Pydantic model before being processed
- Flag: raw `dict` or unvalidated `Any` passed directly into processing functions

#### Type Hints on Public Functions
- Any new or modified public function (no leading `_`) in `src/` missing parameter type hints or return type annotation
- This is mypy strict — `Any` as a workaround also counts as a flag

#### TimescaleDB Date Columns
- Any new database column that stores a timestamp or datetime using `TIMESTAMP` without timezone, `datetime`, or Python `datetime.datetime` without UTC enforcement
- Required: `TIMESTAMPTZ` in SQL DDL; `datetime` with `timezone=True` in SQLAlchemy models

#### Parameterized SQL Only
- Any SQL string built with Python f-strings, `.format()`, or `%` interpolation
- Required: parameterized queries (`%s`, `:param`, or ORM) for all values — even integers

#### PostgreSQL Only (no SQLite in src/)
- Any `sqlite` import or SQLite connection string in `src/`
- SQLite is test-only (`tests/` is fine)

---

## Pass 1 — CRITICAL

#### SQL & Data Safety
- String interpolation in SQL (use parameterized queries — see Pass 0)
- TOCTOU races: check-then-set patterns that should be atomic `WHERE` + `UPDATE`
- N+1 queries: missing batching for loops over DB results

#### Race Conditions & Concurrency
- Read-check-write without uniqueness constraint or conflict handling on concurrent agent writes
- Status transitions on pipeline stages that don't use atomic `WHERE old_status = ? UPDATE SET new_status`

#### LLM Output Trust Boundary
- LLM-generated values (strategy names, ticker symbols, numeric scores) written to DB or passed downstream without format/range validation
- Structured tool output (arrays, dicts from LLM) accepted without shape checks before DB writes or Pydantic parsing
- LLM-generated numeric values (edge scores, probabilities) not clamped to valid ranges before storage

#### Enum & Value Completeness
When the diff introduces a new pipeline stage status, strategy type, signal type, or ticker symbol:
- Trace through every consumer (strategy evaluator, feature generator, output schema). Use Grep → Read (not just grep).
- Check `case`/`if-elif` chains — does the new value fall through to a wrong default?

---

## Pass 2 — INFORMATIONAL

#### Conditional Side Effects
- Pipeline stage functions that branch on a condition but forget to apply a side effect (e.g., logging, DB write) on one branch
- Log messages claiming an action happened when the action was conditionally skipped

#### Magic Numbers & String Coupling
- Bare numeric literals for financial thresholds, score weights, or time windows — should be named constants
- Ticker symbols or strategy names hardcoded in multiple places

#### Dead Code & Consistency
- Variables assigned but never read
- Docstrings or comments describing old behavior after code changed

#### LLM Prompt Issues
- 0-indexed lists in prompts (LLMs reliably return 1-indexed)
- Prompt text listing available tools/capabilities that don't match what's actually wired in the agent
- Score ranges or thresholds stated in both the prompt and code that could drift

#### Test Gaps
- New pipeline stage functions without unit tests
- Tests that assert output type but not value correctness (e.g., "returns a list" but not "list contains expected strategies")
- Missing negative-path tests for invalid input (bad ticker, missing price data, malformed options chain)
- External API calls in tests that should be mocked

#### Completeness Gaps
- Partial Pydantic model coverage (fields typed as `Any` or `dict` where a typed model would cost <15 min CC)
- Missing edge case handling for known data quality issues (NaN prices, empty options chains, zero-volume contracts)
- Features implemented at 80-90% when 100% is achievable with modest additional code

#### Time Window Safety
- Date-key lookups that assume "today" is consistent across timezones — use UTC explicitly
- Mismatched time windows between price ingestion and event detection (e.g., one uses hourly, another daily)

---

## Severity Classification

```
HARD RULES (blocker):             CRITICAL (highest severity):      INFORMATIONAL (lower severity):
├─ LangChain/LangGraph ban        ├─ SQL & Data Safety              ├─ Conditional Side Effects
├─ LLM instantiation outside      ├─ Race Conditions & Concurrency  ├─ Magic Numbers & String Coupling
│  llm_wrapper.py                 ├─ LLM Output Trust Boundary      ├─ Dead Code & Consistency
├─ Missing @with_retry()          └─ Enum & Value Completeness      ├─ LLM Prompt Issues
├─ Missing Pydantic validation                                        ├─ Test Gaps
├─ Missing type hints                                                 ├─ Completeness Gaps
├─ Non-TIMESTAMPTZ date cols                                          └─ Time Window Safety
├─ Non-parameterized SQL
└─ SQLite in src/
```

---

## Fix-First Heuristic

```
AUTO-FIX (agent fixes without asking):     ASK (needs human judgment):
├─ Dead code / unused variables            ├─ Hard rule violations (always ASK)
├─ Stale comments contradicting code       ├─ Security (injection, trust boundary)
├─ Magic numbers → named constants         ├─ Race conditions
├─ Missing LLM output range clamping       ├─ Design decisions
├─ Stale docstrings                        ├─ Large fixes (>20 lines)
└─ Missing test for trivial happy path     ├─ Enum completeness
                                           ├─ Removing functionality
                                           └─ Anything changing agent output schema
```

**Rule of thumb:** If the fix is mechanical and a senior engineer would apply it
without discussion, it's AUTO-FIX. If reasonable engineers could disagree, it's ASK.
Hard rule violations are always ASK — they may indicate a design problem, not just a typo.

---

## Suppressions — DO NOT flag these

- "Add a comment explaining why this threshold was chosen" — thresholds change during tuning, comments rot
- "This assertion could be tighter" when the assertion already covers the behavior
- Suggesting consistency-only changes when the existing pattern is harmless
- Score weight or threshold changes — these are tuned empirically
- `Any` type hints on test helper functions (tests/ only, not src/)
- ANYTHING already addressed in the diff you're reviewing — read the FULL diff before commenting
