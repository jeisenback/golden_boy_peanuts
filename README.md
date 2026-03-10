# Energy Options Opportunity Agent

An autonomous pipeline that identifies options trading opportunities driven by oil market instability. It ingests crude prices, ETF/equity data, options chains, supply events, and news feeds — then ranks explainable options strategies by a composite edge score.

**Instruments:** WTI (CL=F), Brent (BZ=F), USO, XLE, XOM, CVX
**Structures:** Long straddles, call/put spreads, calendar spreads
**Output schema:** `instrument`, `structure`, `expiration`, `edge_score`, `signals`, `generated_at`

---

## Repo Structure

```
.github/
  ISSUE_TEMPLATE/       # feature, bug, chore, test issue templates
  scripts/
    check_runtime_imports.py   # AST scanner — enforces no langchain.* in src/
  workflows/            # ci.yml, integration.yml, runtime-check.yml, security.yml
  pull_request_template.md

docs/
  energy_options_prd.md           # Product requirements and phasing
  energy_options_esod.md          # Engineering standards (non-negotiable constraints)
  energy_options_agent_design_doc.md  # System architecture and data flow
  energy_options_sdlc.md          # Branching, CI/CD, sprint workflow
  energy_options_adlc.md          # Agent-assisted development loop (10 steps)
  prompts/                        # Claude Code prompt templates (5 task types)

scripts/
  new_branch.sh         # Interactive branch creator (enforces SDLC naming + develop base)
  local_check.sh        # Pre-push gate: ruff → black → mypy → import scan
  post_session.sh       # ADLC post-session checklist (run after every agent session)

src/
  core/
    llm_wrapper.py      # Provider-agnostic LLM interface (ESOD 5.3 — use this, not SDKs)
  agents/
    ingestion/          # Fetch + normalize prices, options chains → MarketState
    event_detection/    # News/geo feeds → DetectedEvent list
    feature_generation/ # MarketState + events → FeatureSet (vol gaps, signals, etc.)
    strategy_evaluation/ # FeatureSet → ranked StrategyCandidate list

tests/
  agents/<name>/        # Unit tests (xfail stubs) and integration tests per agent

.env.example            # All required environment variables
requirements.txt        # Runtime dependencies
requirements-dev.txt    # Dev/CI dependencies
pyproject.toml          # ruff, black, mypy, pytest configuration
```

---

## Quickstart

```bash
# 1. Install dependencies
pip install -r requirements-dev.txt

# 2. Copy and configure environment
cp .env.example .env
# Edit .env — set DATABASE_URL and any API keys you have

# 3. Verify no banned imports exist in src/
python .github/scripts/check_runtime_imports.py

# 4. Run the test suite
pytest tests/ -m "not integration" -v
# Expected: all tests XFAIL until agents are implemented

# 5. Run integration tests (requires Docker for testcontainers)
pytest tests/ -m integration -v
```

### Starting a new development session

```bash
# Create a branch (interactive)
bash scripts/new_branch.sh

# After a Claude Code or Cursor session, run the checklist
bash scripts/post_session.sh

# Run the full local quality gate before pushing
bash scripts/local_check.sh
```

---

## Key Constraints (ESOD — Non-Negotiable)

| Rule | Detail |
|------|--------|
| **No langchain.* or langgraph.* in src/** | CI-enforced via `check_runtime_imports.py`. LangChain is dev tooling only. |
| **All LLM calls via `src/core/llm_wrapper.py`** | Never instantiate provider SDKs directly in agent code. |
| **Type hints on all public functions** | mypy strict mode. CI fails on type errors. |
| **Pydantic at every module boundary** | All inbound data validated before processing. |
| **tenacity on all external API calls** | Exponential backoff, configured via env vars. |
| **PostgreSQL only** | DATABASE_URL from environment. SQLite for unit tests only, never staging/prod. |
| **TimescaleDB-compatible schema** | All time-series tables use TIMESTAMPTZ columns from day one. |

---

## Pipeline Data Flow

```
Ingestion Agent
  → MarketState (prices, options chains)
      ↓
Event Detection Agent
  → list[DetectedEvent] (supply disruptions, geo events)
      ↓
Feature Generation Agent
  → FeatureSet (vol gaps, curve steepness, supply shock probability, ...)
      ↓
Strategy Evaluation Agent
  → list[StrategyCandidate] (ranked by edge_score, with signal map)
```

Each agent is independently importable and testable. No agent imports from a downstream agent.

---

## Development Workflow

All work follows the 10-step ADLC loop defined in `docs/energy_options_adlc.md`.

**Branch naming** (from `develop`):
- `feature/<issue>-<slug>` — new capability
- `fix/<issue>-<slug>` — bug fix
- `chore/<issue>-<slug>` — tooling/deps/docs
- `agent/<issue>-<slug>` — Claude Code / Cursor session in progress

**Before every PR:**
1. Run `bash scripts/post_session.sh` and complete the checklist
2. Run `bash scripts/local_check.sh` — all 4 stages must pass
3. Apply `needs-review` label, pause, review as a second developer

**Claude Code prompt templates** are in `docs/prompts/`. Match the template to the task type before starting a session.

---

## MVP Phases

| Phase | Scope | Status |
|-------|-------|--------|
| 1 | Core market signals: crude, ETF/equity prices, options surface, long straddles, spreads | Scaffold only |
| 2 | Supply augmentation: EIA inventory, event detection, supply disruption index | Not started |
| 3 | Alternative signals: insider trades, narrative velocity, shipping data | Not started |
| 4 | Optional enhancements: exotic structures, automated execution | Deferred |

---

## References

- `docs/energy_options_prd.md` — full feature list, acceptance criteria, output schema
- `docs/energy_options_esod.md` — all technical standards and architectural decisions
- `docs/energy_options_agent_design_doc.md` — module responsibilities, data models, DB schema
- `docs/energy_options_sdlc.md` — branching rules, CI stages, sprint cadence
- `docs/energy_options_adlc.md` — development loop, prompt templates, post-session checklist
