# Copilot Instructions

## Project Summary

**Energy Options Opportunity Agent** — a Python 3.11 autonomous pipeline that identifies options trading opportunities driven by oil market instability. It ingests crude prices, ETF/equity data, options chains, supply events, and news feeds, then ranks explainable options strategies by a composite edge score.

**Instruments:** WTI (CL=F), Brent (BZ=F), USO, XLE, XOM, CVX  
**Output schema:** `instrument`, `structure`, `expiration`, `edge_score`, `signals`, `generated_at`

---

## Repository Layout

```
.github/
  copilot-instructions.md       # ← this file
  scripts/check_runtime_imports.py  # AST scanner — CI-enforced no langchain.* in src/
  workflows/                    # ci.yml, integration.yml, runtime-check.yml, security.yml
  ISSUE_TEMPLATE/               # feature, bug, chore, test templates
  pull_request_template.md

docs/
  energy_options_esod.md        # Non-negotiable engineering standards
  energy_options_prd.md         # Product requirements and acceptance criteria
  energy_options_agent_design_doc.md  # Architecture, data flow, DB schema
  energy_options_sdlc.md        # Branching rules, CI/CD, sprint workflow
  energy_options_adlc.md        # 10-step agent-assisted development loop
  prompts/                      # Claude Code / Cursor prompt templates

scripts/
  local_check.sh                # Pre-push gate: ruff → black → mypy → import scan
  new_branch.sh                 # Interactive branch creator (enforces SDLC naming)
  post_session.sh               # ADLC post-session checklist

src/
  core/llm_wrapper.py           # Provider-agnostic LLM interface — use this, never SDKs
  agents/
    ingestion/                  # Fetch + normalize prices, options chains → MarketState
    event_detection/            # News/geo feeds → list[DetectedEvent]
    feature_generation/         # MarketState + events → FeatureSet
    strategy_evaluation/        # FeatureSet → ranked list[StrategyCandidate]

tests/
  agents/<name>/                # Unit tests (xfail stubs) and integration tests per agent

pyproject.toml                  # ruff, black, mypy, pytest configuration
requirements.txt                # Runtime dependencies
requirements-dev.txt            # Dev/CI dependencies (includes runtime deps)
.env.example                    # All required environment variables
```

---

## Setup

```bash
# Install all dependencies (always run first after cloning)
pip install -r requirements-dev.txt

# Copy environment variables
cp .env.example .env
# Set DATABASE_URL and any API keys in .env
```

---

## Build & Validate

Always run the **local quality gate** before pushing. It mirrors all CI stages:

```bash
bash scripts/local_check.sh
# Runs in order: ruff → black → mypy → runtime import scan
# Must show ALL STAGES PASSED before pushing
```

Individual stages (Python 3.11 required):

```bash
ruff check src/ tests/          # Lint (line-length 100, strict ruleset)
black --check src/ tests/       # Format check (line-length 100)
mypy src/                       # Type check (strict mode — all public functions need hints)
python .github/scripts/check_runtime_imports.py  # Enforces no langchain.*/langgraph.* in src/
```

**Important:** Never use `ruff --fix` or `black` (auto-format) in CI — fix locally only.

---

## Testing

```bash
# Unit tests (fast, no external services)
pytest tests/ -m "not integration" --tb=short -v
# Expected: all tests XFAIL while agents are scaffolds

# Integration tests (requires Docker for testcontainers + Postgres)
pytest tests/ -m integration -v
```

Test configuration is in `pyproject.toml` under `[tool.pytest.ini_options]`.  
Markers: `unit` (mocked deps) and `integration` (requires running Postgres).  
SQLite is allowed in unit tests only — never in staging or production.

---

## Non-Negotiable Constraints (ESOD)

| Rule | Detail |
|------|--------|
| **No `langchain.*` / `langgraph.*` in `src/`** | CI-enforced via `check_runtime_imports.py`. LangChain is dev tooling only. |
| **All LLM calls via `src/core/llm_wrapper.py`** | Never instantiate provider SDKs directly in agent code. |
| **Type hints on all public functions** | mypy strict — CI fails on any type error. |
| **Pydantic at every module boundary** | All inbound data must be validated before processing. |
| **tenacity on all external API calls** | Exponential backoff; configure via env vars. |
| **PostgreSQL only** | `DATABASE_URL` from environment; SQLite for unit tests only. |
| **TimescaleDB-compatible schema** | All time-series columns must use `TIMESTAMPTZ`. |
| **Agent isolation** | No agent imports from a downstream agent in the pipeline. |

---

## CI Pipeline (GitHub Actions)

| Workflow | Trigger | What it checks |
|----------|---------|---------------|
| `ci.yml` | push / PR | ruff, black, mypy, unit tests |
| `integration.yml` | push / PR | Integration tests with real Postgres |
| `runtime-check.yml` | push / PR | `check_runtime_imports.py` — banned import scan |
| `security.yml` | push / PR | bandit (SAST), pip-audit (dependency CVEs) |

All four workflows must pass before merging.

---

## Branch Naming (from `develop`)

- `feature/<issue>-<slug>` — new capability  
- `fix/<issue>-<slug>` — bug fix  
- `chore/<issue>-<slug>` — tooling/deps/docs  
- `agent/<issue>-<slug>` — active Claude Code / Cursor session  

Use `bash scripts/new_branch.sh` to create branches interactively.

---

## Pipeline Data Flow

```
Ingestion Agent → MarketState
  → Event Detection Agent → list[DetectedEvent]
    → Feature Generation Agent → FeatureSet
      → Strategy Evaluation Agent → list[StrategyCandidate] (ranked by edge_score)
```

Each agent lives in `src/agents/<name>/` and contains: `<name>_agent.py`, `models.py`, `db.py`.

---

Trust these instructions. Only search the codebase if you need detail not covered above or if something appears to be out of date.
