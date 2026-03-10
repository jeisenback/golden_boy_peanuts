# Prompt Template: New Agent Module

**When to use:** Creating a new top-level agent module
(e.g., ingestion agent, event detection agent, feature generation agent).

**Reference:** ADLC Section 5.1

---

## Copy this prompt into your Claude Code session:

---

You are implementing a new agent module for the Energy Options Opportunity Agent system.

GITHUB ISSUE: #[ISSUE_NUMBER] — [ISSUE_TITLE]

PRD REFERENCE: Section [X] — [SECTION_NAME]

MODULE: [module_name]
(e.g., ingestion_agent | event_detection_agent | feature_generation_agent | strategy_evaluation_agent)

LOCATION: src/agents/[module_name]/

RESPONSIBILITIES:
[List exactly what this module must do — one item per line]

INPUTS:
[Describe what data/config this module receives.
Pydantic model name and fields if known.]

OUTPUTS:
[Describe the exact output: data structure, field names, types.
Reference PRD Section 9 candidate output schema if output-facing.]

CONSTRAINTS (from ESOD — non-negotiable):
- Python 3.11+. Type hints on ALL public functions. No exceptions.
- No langchain.* or langgraph.* imports anywhere in src/.
- All external API calls must use tenacity for retry with exponential backoff and jitter.
- All inbound data validated with Pydantic models at the module boundary.
- Structured JSON logging using the Python logging module (not print statements).
- Module must operate correctly if called without any LangChain dependency installed.

DATABASE:
- PostgreSQL via psycopg2 or SQLAlchemy. Schema must be TimescaleDB-compatible.
  (Use timestamp columns with explicit timezone; avoid SQLite-specific SQL.)
- Connection string read exclusively from environment variable: DATABASE_URL
- Do not hardcode any connection parameters.

EXPECTED FILE STRUCTURE:
src/agents/[module_name]/
    __init__.py
    [module_name].py          # main agent logic
    models.py                 # Pydantic input/output models
    db.py                     # database read/write functions

tests/agents/[module_name]/
    __init__.py
    test_[module_name].py     # unit tests (mocked dependencies)
    test_[module_name]_integration.py   # integration tests (testcontainers Postgres)

DO NOT:
- Make architecture decisions not specified here. If a decision is ambiguous, ask.
- Import from langchain, langgraph, or any agent framework.
- Use SQLite for any database operations.
- Leave unimplemented stubs without a TODO comment and a corresponding failing test.
- Use bare except clauses. Log exceptions with context.

Start by reading the existing codebase structure (src/ and tests/).
Then implement the module. Then write the tests.

---

## Variable Checklist Before Pasting

- [ ] `[ISSUE_NUMBER]` replaced
- [ ] `[ISSUE_TITLE]` replaced
- [ ] `[X]` PRD section number replaced
- [ ] `[SECTION_NAME]` replaced
- [ ] `[module_name]` replaced in all locations
- [ ] RESPONSIBILITIES section filled in
- [ ] INPUTS section filled in
- [ ] OUTPUTS section filled in
