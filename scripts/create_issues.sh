#!/usr/bin/env bash
# create_issues.sh
#
# Creates all GitHub labels, milestones, and issues for the Energy Options
# Opportunity Agent project. Run once after initializing the GitHub repository.
#
# Usage:
#   gh auth login          # if not already authenticated
#   bash scripts/create_issues.sh
#
# Idempotent: label/milestone creation uses `|| true` so reruns are safe.
# Issues are NOT idempotent — do not run twice or duplicates will be created.

set -euo pipefail

REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || echo "")
if [[ -z "$REPO" ]]; then
  echo "ERROR: Not inside a GitHub repository. Run 'gh repo create' first."
  exit 1
fi

echo ""
echo "=== Creating issues for: ${REPO} ==="
echo ""

# ---------------------------------------------------------------------------
# Helper: write issue body to temp file, create issue, clean up
# ---------------------------------------------------------------------------
create_issue() {
  local title="$1"
  local labels="$2"
  local milestone="$3"
  local body="$4"
  local tmp
  tmp=$(mktemp)
  printf '%s' "$body" > "$tmp"
  gh issue create \
    --title "$title" \
    --label "$labels" \
    --milestone "$milestone" \
    --body-file "$tmp"
  rm -f "$tmp"
  echo "  Created: ${title}"
}

# ---------------------------------------------------------------------------
# LABELS
# ---------------------------------------------------------------------------
echo "--- Creating labels ---"

gh label create "type: feature"  --color "0075ca" --description "New capability, agent, signal, or data source"          --force
gh label create "type: fix"      --color "d93f0b" --description "Bug or defect correction"                               --force
gh label create "type: chore"    --color "e4e669" --description "Tooling, deps, docs, or non-functional changes"         --force
gh label create "type: test"     --color "fbca04" --description "Test coverage gap or golden dataset"                    --force
gh label create "type: infra"    --color "5319e7" --description "Infrastructure, schema, environment setup"              --force
gh label create "type: refactor" --color "bfd4f2" --description "Code improvement with zero behavioral changes"          --force
gh label create "type: qa"       --color "f9d0c4" --description "QA sign-off and coverage validation"                    --force
gh label create "type: uat"      --color "0e8a16" --description "User acceptance testing against live conditions"        --force
gh label create "type: release"  --color "006b75" --description "Release preparation, tagging, and deployment"           --force
gh label create "phase: 0"       --color "c5def5" --description "Phase 0 — Project setup"                               --force
gh label create "phase: 1"       --color "c5def5" --description "Phase 1 — Core Market Signals & Options"               --force
gh label create "phase: 2"       --color "bfe5bf" --description "Phase 2 — Supply & Event Augmentation"                 --force
gh label create "phase: 3"       --color "fef2c0" --description "Phase 3 — Alternative / Contextual Signals"            --force
gh label create "phase: 4"       --color "f9d0c4" --description "Phase 4 — Optional Enhancements"                       --force
gh label create "agent-assisted" --color "d4c5f9" --description "Partially or fully implemented using Claude Code / Cursor / Copilot" --force
gh label create "blocked"        --color "b60205" --description "Cannot proceed — waiting on dependency or decision"     --force
gh label create "needs-review"   --color "e4e669" --description "Ready for self-review pause before merge"              --force

echo "Labels created."
echo ""

# ---------------------------------------------------------------------------
# MILESTONES
# ---------------------------------------------------------------------------
echo "--- Creating milestones ---"

gh api repos/"$REPO"/milestones --method POST \
  --field title="Phase 0: Project Setup" \
  --field description="Repository initialization, local environment, CI verification, and DRY/SOLID refactors." \
  > /dev/null || true

gh api repos/"$REPO"/milestones --method POST \
  --field title="Phase 1: Core Market Signals & Options" \
  --field description="Crude benchmarks (WTI, Brent), USO/XLE/XOM/CVX prices, options surface analysis, long straddles and call/put spreads, ranked candidate output." \
  > /dev/null || true

gh api repos/"$REPO"/milestones --method POST \
  --field title="Phase 2: Supply & Event Augmentation" \
  --field description="EIA inventory, event detection via GDELT/NewsAPI, supply disruption indices, event-driven edge scoring." \
  > /dev/null || true

gh api repos/"$REPO"/milestones --method POST \
  --field title="Phase 3: Alternative / Contextual Signals" \
  --field description="Insider trades (EDGAR/Quiver), narrative velocity (Reddit/Stocktwits), shipping data (MarineTraffic), full-layer edge scoring." \
  > /dev/null || true

gh api repos/"$REPO"/milestones --method POST \
  --field title="Phase 4: Optional Enhancements" \
  --field description="OPIS pricing, exotic/multi-legged structures, automated execution integration." \
  > /dev/null || true

echo "Milestones created."
echo ""

# ---------------------------------------------------------------------------
# PHASE 0 ISSUES — Project Setup
# ---------------------------------------------------------------------------
echo "--- Phase 0: Project Setup ---"

create_issue \
  "Initialize GitHub repository: labels, milestones, branch protection" \
  "type: infra,type: chore,phase: 0" \
  "Phase 0: Project Setup" \
  "## Goal
Configure the GitHub repository for production-ready development workflow per SDLC Section 3 and 4.

## Context
The repository exists but has no branch protection, labels, or milestones. This issue is closed by running \`bash scripts/create_issues.sh\` which creates all labels/milestones, and by configuring branch protection manually on GitHub.

## Acceptance Criteria
- [ ] All labels created (type: feature/fix/chore/test/infra/refactor/qa/uat/release, phase: 0/1/2/3/4, agent-assisted, blocked, needs-review)
- [ ] All milestones created (Phase 0 through Phase 4)
- [ ] \`main\` branch protection enabled: require PR before merge, require CI status checks (CI, Runtime Import Check)
- [ ] \`develop\` branch created and pushed
- [ ] \`develop\` set as the default branch for PRs
- [ ] CODEOWNERS or single maintainer confirmed in repo settings

## Notes
Branch protection is configured at: Settings → Branches → Add rule → main.
Required status checks: 'CI / Lint & Format Check', 'CI / mypy Strict Type Check', 'CI / Unit Tests', 'Runtime Import Check / Runtime Import Check (ESOD Architectural Rule)'."

create_issue \
  "Local development environment: Docker Compose for Postgres, venv, .env setup" \
  "type: infra,type: chore,phase: 0" \
  "Phase 0: Project Setup" \
  "## Goal
Establish a reproducible local development environment that every developer (and every Claude Code session) can set up from scratch in under 10 minutes.

## Context
The project requires PostgreSQL 15+ locally for integration tests and development. The current repo has \`.env.example\` and \`requirements-dev.txt\` but no Docker Compose setup for the database. Every integration test uses testcontainers, but active development against a persistent local DB requires a running Postgres instance.

## Acceptance Criteria
- [ ] \`docker-compose.yml\` created at repo root with a Postgres 15 service (port 5432, persistent volume, credentials matching \`.env.example\` defaults)
- [ ] \`README.md\` local setup section updated with exact commands: \`docker compose up -d\`, \`pip install -r requirements-dev.txt\`, \`cp .env.example .env\`
- [ ] Running \`python .github/scripts/check_runtime_imports.py\` from repo root exits 0
- [ ] Running \`pytest tests/ -m 'not integration'\` passes (all xfail, no errors)
- [ ] Running \`docker compose up -d && pytest tests/ -m integration\` passes (once integration tests exist)
- [ ] \`docker-compose.yml\` added to \`.gitignore\` exclusion list confirmed NOT excluded — it should be committed

## Technical Notes
- Postgres service name: \`db\`
- Default credentials (matching \`.env.example\`): user=postgres, password=password, db=energy_options
- Volume name: \`energy_options_pgdata\`
- Add a \`healthcheck\` so dependent services can wait for Postgres to be ready
- Do NOT commit actual \`.env\` — only \`.env.example\` is committed"

create_issue \
  "Refactor: extract shared get_engine() to src/core/db.py (DRY)" \
  "type: refactor,type: chore,phase: 0" \
  "Phase 0: Project Setup" \
  "## Goal
Remove the identical \`get_engine()\` function duplicated across all four agent \`db.py\` files and replace with a single shared implementation in \`src/core/db.py\`.

## Context
The current scaffold contains four identical copies of \`get_engine()\` in:
- \`src/agents/ingestion/db.py\`
- \`src/agents/event_detection/db.py\`
- \`src/agents/feature_generation/db.py\`
- \`src/agents/strategy_evaluation/db.py\`

This is a DRY violation. A bug fix or configuration change to \`get_engine()\` (e.g. adding connection pooling parameters, SSL mode, or connection timeout) would need to be made in four places. Extract to \`src/core/db.py\` now, before agent implementations begin and the duplication compounds.

## Acceptance Criteria
- [ ] \`src/core/db.py\` created with a single \`get_engine()\` implementation
- [ ] All four agent \`db.py\` files import \`get_engine\` from \`src.core.db\` instead of defining it locally
- [ ] \`get_engine()\` in \`src/core/db.py\` has full type hints and docstring
- [ ] \`src/core/db.py\` includes a module-level docstring explaining its role
- [ ] All four agent \`db.py\` files have their local \`get_engine()\` definitions removed
- [ ] Zero behavioral changes: \`pytest tests/ -m 'not integration'\` passes without modification
- [ ] \`ruff check src/\` and \`mypy src/\` pass
- [ ] \`python .github/scripts/check_runtime_imports.py\` exits 0

## Constraints
- This is a pure refactor. No new functionality, no new parameters, no new dependencies.
- Do not change any function signatures in the agent \`db.py\` files.
- Reference: ADLC Section 5.5 (Refactor/Cleanup template)"

create_issue \
  "Refactor: extract shared tenacity retry config to src/core/retry.py (DRY)" \
  "type: refactor,type: chore,phase: 0" \
  "Phase 0: Project Setup" \
  "## Goal
Remove the duplicated tenacity retry decorator configuration spread across agent files and provide a single \`with_retry()\` decorator factory in \`src/core/retry.py\`.

## Context
The tenacity retry configuration:
\`\`\`python
@retry(
    stop=stop_after_attempt(int(os.environ.get(\"TENACITY_MAX_RETRIES\", \"5\"))),
    wait=wait_exponential(
        multiplier=int(os.environ.get(\"TENACITY_WAIT_MULTIPLIER\", \"1\")),
        max=int(os.environ.get(\"TENACITY_WAIT_MAX\", \"60\")),
    ),
    reraise=True,
)
\`\`\`
is already duplicated in \`ingestion_agent.py\` and \`event_detection_agent.py\` and will be duplicated again in every fetch function across all agents. Centralizing it means retry policy changes (e.g. adding \`before_sleep\` logging, changing jitter strategy) happen in one place.

## Acceptance Criteria
- [ ] \`src/core/retry.py\` created with a \`with_retry()\` function that returns a configured tenacity \`retry\` decorator
- [ ] \`with_retry()\` reads \`TENACITY_MAX_RETRIES\`, \`TENACITY_WAIT_MULTIPLIER\`, \`TENACITY_WAIT_MAX\` from environment with the same defaults as current code
- [ ] \`with_retry()\` adds \`before_sleep\` logging (log the exception and retry attempt number at WARNING level)
- [ ] Both \`ingestion_agent.py\` and \`event_detection_agent.py\` updated to use \`@with_retry()\` instead of the inline \`@retry(...)\" decorator block
- [ ] Full type hints and docstring on \`with_retry()\`
- [ ] Zero behavioral changes: \`pytest tests/ -m 'not integration'\` passes without modification
- [ ] \`ruff check src/\` and \`mypy src/\` pass
- [ ] \`python .github/scripts/check_runtime_imports.py\` exits 0

## Constraints
- Pure refactor. The retry behavior (attempts, wait, reraise) must be identical to the current inline config.
- Do not add new env vars or change existing defaults.
- Depends on: #3 (src/core/db.py exists — establishes the core/ shared utilities pattern)"

create_issue \
  "CI pipeline verification: confirm all 4 workflows run green on initial scaffold" \
  "type: chore,type: test,phase: 0" \
  "Phase 0: Project Setup" \
  "## Goal
Verify that all four GitHub Actions workflows execute and pass on the initial scaffold before any feature work begins.

## Context
The four workflows (\`ci.yml\`, \`integration.yml\`, \`runtime-check.yml\`, \`security.yml\`) were written as part of the initial scaffold but have never executed against the real repository. This issue ensures CI is a reliable gate before it is depended upon for feature work.

## Acceptance Criteria
- [ ] Push scaffold to \`develop\` triggers \`ci.yml\`: lint, format check, mypy, and unit tests all pass
- [ ] \`runtime-check.yml\` runs and exits 0 (no banned imports in src/)
- [ ] Open a PR from \`develop\` to \`main\` triggers \`integration.yml\`: runs and collects 0 items (no integration tests yet — acceptable at this stage)
- [ ] \`security.yml\` triggers on PR to \`main\` and passes (no HIGH severity bandit findings, pip-audit clean)
- [ ] All workflow run results visible in the GitHub Actions tab with green status
- [ ] Any CI failure is investigated and fixed before this issue is closed — do not close with a known failure

## Notes
- Unit tests will show '9 xfailed' — this is the expected result at scaffold stage
- If mypy strict mode fails on any scaffold file, fix it here before opening feature issues
- If bandit flags any scaffold code, either fix or suppress with explicit \`# nosec\` comment and document why"

echo ""

# ---------------------------------------------------------------------------
# PHASE 1 ISSUES — Infrastructure
# ---------------------------------------------------------------------------
echo "--- Phase 1: Infrastructure ---"

create_issue \
  "PostgreSQL schema: market_prices and options_chain tables" \
  "type: infra,type: feature,phase: 1" \
  "Phase 1: Core Market Signals & Options" \
  "## Goal
Define and apply the PostgreSQL DDL for the two Ingestion Agent tables: \`market_prices\` and \`options_chain\`.

## Context
PRD Section 6.1 requires PostgreSQL 15+ with TimescaleDB-compatible schema from day one. This means:
- All time-series tables must use a \`TIMESTAMPTZ\` column (not \`TIMESTAMP\` without timezone)
- No SQLite-specific syntax
- Schema must support future \`SELECT create_hypertable('table', 'timestamp')\` without SQL changes

These tables are the write targets for the Ingestion Agent. No agent implementation can be merged until this schema exists and is applied to the local dev database.

## Acceptance Criteria
- [ ] \`db/schema.sql\` file created (new directory) containing DDL for \`market_prices\` and \`options_chain\`
- [ ] \`market_prices\` columns: \`id BIGSERIAL PRIMARY KEY\`, \`instrument TEXT NOT NULL\`, \`instrument_type TEXT NOT NULL\`, \`price NUMERIC(18,6) NOT NULL\`, \`volume BIGINT\`, \`source TEXT NOT NULL\`, \`timestamp TIMESTAMPTZ NOT NULL\`
- [ ] \`options_chain\` columns: \`id BIGSERIAL PRIMARY KEY\`, \`instrument TEXT NOT NULL\`, \`strike NUMERIC(18,6) NOT NULL\`, \`expiration_date TIMESTAMPTZ NOT NULL\`, \`implied_volatility NUMERIC(10,6)\`, \`open_interest BIGINT\`, \`volume BIGINT\`, \`option_type TEXT NOT NULL CHECK (option_type IN ('call','put'))\`, \`source TEXT NOT NULL\`, \`timestamp TIMESTAMPTZ NOT NULL\`
- [ ] Index on \`market_prices(instrument, timestamp DESC)\`
- [ ] Index on \`options_chain(instrument, expiration_date)\`
- [ ] \`db/README.md\` (or a comment block in \`schema.sql\`) notes which columns are the TimescaleDB hypertable candidates and the migration trigger criteria from PRD Section 6.2
- [ ] Schema applied to local dev Postgres and verified with \`\\d market_prices\` and \`\\d options_chain\` in psql
- [ ] No ORM models or SQLAlchemy table definitions yet — raw SQL only at this stage

## Notes
- Place schema file at \`db/schema.sql\` — a \`db/\` directory for all raw SQL/migration assets
- Calendar spreads require two legs; the options_chain schema does not need to model this yet — single-leg records are sufficient for Phase 1"

create_issue \
  "PostgreSQL schema: feature_sets and strategy_candidates tables" \
  "type: infra,type: feature,phase: 1" \
  "Phase 1: Core Market Signals & Options" \
  "## Goal
Define and apply the PostgreSQL DDL for the two output tables: \`feature_sets\` and \`strategy_candidates\`.

## Context
Companion to the ingestion schema issue. These tables are the write targets for the Feature Generation and Strategy Evaluation agents. The \`strategy_candidates\` table is the primary output of the Phase 1 system and must match the PRD Section 9 output schema exactly.

## Acceptance Criteria
- [ ] DDL added to \`db/schema.sql\` for \`feature_sets\` and \`strategy_candidates\`
- [ ] \`feature_sets\` columns: \`id BIGSERIAL PRIMARY KEY\`, \`snapshot_time TIMESTAMPTZ NOT NULL\`, \`volatility_gaps JSONB\`, \`futures_curve_steepness NUMERIC(10,6)\`, \`sector_dispersion NUMERIC(10,6)\`, \`insider_conviction_score NUMERIC(5,4)\`, \`narrative_velocity NUMERIC(10,6)\`, \`supply_shock_probability NUMERIC(5,4)\`, \`feature_errors JSONB\`
- [ ] \`strategy_candidates\` columns: \`id BIGSERIAL PRIMARY KEY\`, \`instrument TEXT NOT NULL\`, \`structure TEXT NOT NULL CHECK (structure IN ('long_straddle','call_spread','put_spread','calendar_spread'))\`, \`expiration INTEGER NOT NULL\`, \`edge_score NUMERIC(5,4) NOT NULL CHECK (edge_score BETWEEN 0 AND 1)\`, \`signals JSONB NOT NULL\`, \`generated_at TIMESTAMPTZ NOT NULL\`
- [ ] Index on \`feature_sets(snapshot_time DESC)\`
- [ ] Index on \`strategy_candidates(generated_at DESC, edge_score DESC)\`
- [ ] Schema verified in local dev Postgres with \`\\d feature_sets\` and \`\\d strategy_candidates\`
- [ ] \`strategy_candidates\` schema reviewed against PRD Section 9 output schema — all fields present with correct types

## Notes
- JSONB used for \`signals\`, \`volatility_gaps\`, and \`feature_errors\` — flexible enough to evolve across phases without schema migrations
- Depends on: #6 (db/schema.sql file and db/ directory already created)"

echo ""

# ---------------------------------------------------------------------------
# PHASE 1 ISSUES — Ingestion Agent
# ---------------------------------------------------------------------------
echo "--- Phase 1: Ingestion Agent ---"

create_issue \
  "Implement fetch_crude_prices — Alpha Vantage (WTI, Brent)" \
  "type: feature,phase: 1,agent-assisted" \
  "Phase 1: Core Market Signals & Options" \
  "## Goal
Implement \`fetch_crude_prices()\` in \`src/agents/ingestion/ingestion_agent.py\` to fetch current WTI (CL=F) and Brent (BZ=F) prices from Alpha Vantage.

## Context
PRD Section 4.1 and Data Sources table (Section 8): Alpha Vantage is the primary source for crude futures prices. This is the first live data feed in the pipeline. The tenacity \`@with_retry()\` decorator and \`RawPriceRecord\` Pydantic model are already in place — this issue implements the body only.

## Acceptance Criteria
- [ ] \`fetch_crude_prices()\` calls Alpha Vantage \`GLOBAL_QUOTE\` endpoint for both \`CL=F\` (WTI) and \`BZ=F\` (Brent)
- [ ] API key read exclusively from \`ALPHA_VANTAGE_API_KEY\` environment variable — never hardcoded
- [ ] Each response validated through \`RawPriceRecord\` Pydantic model before returning
- [ ] Malformed API response raises \`ValueError\` with the raw response included in the message (for quarantine logging by \`run_ingestion\`)
- [ ] \`instrument_type\` set to \`InstrumentType.CRUDE_FUTURES\`
- [ ] \`source\` field set to \`\"alpha_vantage\"\`
- [ ] \`timestamp\` set to UTC datetime of the fetch, not the API's reported quote time
- [ ] Unit tests: mock \`requests.get\`; test successful response, malformed response, and missing API key
- [ ] All tests pass; \`ruff\`, \`mypy\`, import scan pass

## Agent Notes
Use prompt template: \`docs/prompts/feature_existing_module.md\`
ESOD constraints: tenacity already wired via \`@with_retry()\` from \`src/core/retry.py\` — do not add inline retry logic.

## Depends On
- #4 (src/core/retry.py — with_retry() decorator)
- #3 (src/core/db.py — shared engine)"

create_issue \
  "Implement fetch_etf_equity_prices — yfinance (USO, XLE, XOM, CVX)" \
  "type: feature,phase: 1,agent-assisted" \
  "Phase 1: Core Market Signals & Options" \
  "## Goal
Implement \`fetch_etf_equity_prices()\` in \`src/agents/ingestion/ingestion_agent.py\` to fetch current prices for USO, XLE, XOM, and CVX via yfinance.

## Context
PRD Section 8 data sources: Yahoo Finance / yfinance for ETF and equity prices. No API key required for basic yfinance access. These four instruments are the equity/ETF layer of the Phase 1 market state (PRD Section 10, Phase 1 scope).

## Acceptance Criteria
- [ ] \`fetch_etf_equity_prices()\` fetches current price for all four instruments: USO, XLE, XOM, CVX
- [ ] Uses \`yfinance.Ticker(symbol).fast_info\` or equivalent for minimal-latency price fetch
- [ ] Each result validated through \`RawPriceRecord\` Pydantic model
- [ ] \`instrument_type\` set correctly: USO and XLE as \`InstrumentType.ETF\`; XOM and CVX as \`InstrumentType.EQUITY\`
- [ ] \`source\` field set to \`\"yfinance\"\`
- [ ] If a single ticker fetch fails (e.g. yfinance timeout), that ticker's failure is logged and the exception is re-raised — \`run_ingestion\` decides degraded-mode behavior, not this function
- [ ] Unit tests: mock yfinance; test normal response, single-ticker failure, all-tickers failure
- [ ] All tests pass; \`ruff\`, \`mypy\`, import scan pass

## Agent Notes
Use prompt template: \`docs/prompts/feature_existing_module.md\`
Note: yfinance is not async. Do not introduce async/await — synchronous fetches are correct for Phase 1.

## Depends On
- #4 (src/core/retry.py)"

create_issue \
  "Implement fetch_options_chain — yfinance / Polygon (IV, strike, expiry, volume)" \
  "type: feature,phase: 1,agent-assisted" \
  "Phase 1: Core Market Signals & Options" \
  "## Goal
Implement \`fetch_options_chain()\` in \`src/agents/ingestion/ingestion_agent.py\` to fetch options chain data (strike, expiry, IV, volume, open interest) for all in-scope instruments.

## Context
PRD Section 4.1 and Data Sources Section 8: options data is available from Yahoo Finance (free, daily granularity) and Polygon.io (limited free tier). Phase 1 requires IV for \`compute_volatility_gap\` — this is a hard dependency for Feature Generation. yfinance provides \`.options\` and \`.option_chain()\` methods.

## Acceptance Criteria
- [ ] \`fetch_options_chain(instruments: list[str]) -> list[OptionRecord]\` implemented
- [ ] For each instrument, fetches available expiry dates and the nearest 2-3 expiry option chains
- [ ] Each record validated through \`OptionRecord\` Pydantic model
- [ ] \`source\` field set to \`\"yfinance\"\` or \`\"polygon\"\` depending on which client succeeded
- [ ] If Polygon key is absent (\`POLYGON_API_KEY\` not set), falls back to yfinance without raising — logs a WARNING
- [ ] Records with missing IV (\`impliedVolatility\` is NaN in yfinance) set \`implied_volatility=None\` — not filtered out
- [ ] Unit tests: mock yfinance option_chain output; test IV present, IV absent (NaN), expiry fetch failure
- [ ] All tests pass; \`ruff\`, \`mypy\`, import scan pass

## Agent Notes
Use prompt template: \`docs/prompts/feature_existing_module.md\`
yfinance option_chain returns a namedtuple with \`.calls\` and \`.puts\` DataFrames. Map columns: \`strike\`, \`expiration\` (from the expiry date passed to \`option_chain()\`), \`impliedVolatility\`, \`openInterest\`, \`volume\`, option type.

## Depends On
- #4 (src/core/retry.py)"

create_issue \
  "Implement run_ingestion — orchestration, MarketState build, DB persist" \
  "type: feature,phase: 1,agent-assisted" \
  "Phase 1: Core Market Signals & Options" \
  "## Goal
Implement \`run_ingestion()\` in \`src/agents/ingestion/ingestion_agent.py\` — the top-level orchestration function that fetches all feeds, builds a \`MarketState\`, persists to PostgreSQL, and returns the state for downstream agents.

## Context
PRD Section 4.1 non-functional requirement: 'Tolerate delayed or missing data without pipeline failure.' This function is the resilience boundary. It catches individual feed failures, logs them with context, populates \`MarketState.ingestion_errors\`, and returns a partial-but-valid state — it must never raise on a single feed failure.

## Acceptance Criteria
- [ ] Calls \`fetch_crude_prices()\`, \`fetch_etf_equity_prices()\`, \`fetch_options_chain()\` — each in a try/except
- [ ] On individual feed failure: exception message appended to \`ingestion_errors\`; other feeds continue
- [ ] \`MarketState\` built from all successfully fetched records
- [ ] \`write_price_records()\` and \`write_option_records()\` called via \`src/agents/ingestion/db.py\`
- [ ] Structured JSON log emitted at the end of each cycle: instruments fetched count, options records count, error count, duration_ms
- [ ] If ALL feeds fail, \`run_ingestion()\` still returns a \`MarketState\` with empty lists and populated \`ingestion_errors\` — it does not raise
- [ ] Unit tests: mock all three fetch functions; test all-success, one-feed-failure, all-feeds-failure
- [ ] \`ruff\`, \`mypy\`, import scan pass

## Agent Notes
Use prompt template: \`docs/prompts/feature_existing_module.md\`
The INSTRUMENTS_IN_SCOPE list is defined in strategy_evaluation_agent.py — import it or define a shared constant in src/core/constants.py to avoid the circular import.

## Depends On
- #6 (schema: market_prices, options_chain)
- #3 (src/core/db.py)
- #8 (fetch_crude_prices)
- #9 (fetch_etf_equity_prices)
- #10 (fetch_options_chain)"

create_issue \
  "QA: Ingestion Agent — integration test and coverage sign-off" \
  "type: qa,type: test,phase: 1" \
  "Phase 1: Core Market Signals & Options" \
  "## Goal
Validate the Ingestion Agent against a real PostgreSQL instance and sign off that unit + integration coverage meets the Phase 1 quality bar before Feature Generation work begins.

## Context
Per ADLC Section 6, a new agent module is not done until it has: unit tests for all public functions, an integration test covering the full pipeline path through the module, and no langchain.* runtime imports. This issue is the formal QA gate for the Ingestion Agent.

## Acceptance Criteria

### Integration Tests (testcontainers — real Postgres, no mocks)
- [ ] \`tests/agents/ingestion/test_ingestion_agent_integration.py\` created
- [ ] Test: \`run_ingestion()\` with mocked feed responses writes rows to \`market_prices\` and \`options_chain\` tables; assert row counts and field values
- [ ] Test: \`run_ingestion()\` with one feed mocked to raise writes partial records and populates \`ingestion_errors\`
- [ ] Test: \`write_price_records()\` and \`write_option_records()\` round-trip: write N records, query DB, assert N rows with correct values
- [ ] All integration tests use \`testcontainers.postgres.PostgresContainer\` — no mocked DB

### Unit Test Coverage
- [ ] \`fetch_crude_prices()\`: success, malformed response, API key absent
- [ ] \`fetch_etf_equity_prices()\`: success, single-ticker failure
- [ ] \`fetch_options_chain()\`: success, NaN IV handling, Polygon fallback
- [ ] \`run_ingestion()\`: all-success, partial failure, all-failure

### Coverage and Quality
- [ ] \`pytest --cov=src/agents/ingestion\` shows >80% line coverage
- [ ] \`ruff\`, \`mypy src/agents/ingestion/\`, import scan all pass
- [ ] All existing xfail test stubs for this agent replaced with real passing tests

## Depends On
- #11 (run_ingestion fully implemented)"

echo ""

# ---------------------------------------------------------------------------
# PHASE 1 ISSUES — Feature Generation Agent
# ---------------------------------------------------------------------------
echo "--- Phase 1: Feature Generation Agent ---"

create_issue \
  "Implement compute_volatility_gap — realized vs. implied volatility" \
  "type: feature,phase: 1,agent-assisted" \
  "Phase 1: Core Market Signals & Options" \
  "## Goal
Implement \`compute_volatility_gap()\` in \`src/agents/feature_generation/feature_generation_agent.py\` to compute the realized vs. implied volatility gap for each instrument in the MarketState.

## Context
PRD Section 4.3: 'Volatility gaps (realized vs. implied)' is the primary Phase 1 signal. A positive gap (IV > realized vol) indicates the market is pricing in more uncertainty than recent price action suggests — a key input for straddle edge scoring. Realized vol is calculated from price history stored by the Ingestion Agent. Implied vol comes from \`OptionRecord.implied_volatility\` in the current MarketState.

## Acceptance Criteria
- [ ] \`compute_volatility_gap(market_state: MarketState) -> list[VolatilityGap]\` implemented
- [ ] Realized volatility computed as annualized 30-day historical volatility from \`market_prices\` DB records (log returns, annualized by × sqrt(252))
- [ ] Implied volatility taken as the ATM (at-the-money) implied vol for the nearest expiry from \`market_state.options\`
- [ ] ATM strike selection: option with strike closest to current price for the instrument
- [ ] If fewer than 10 price history records exist for an instrument, that instrument is skipped with a WARNING log — not an error
- [ ] If no options data exists for an instrument, it is skipped with a WARNING — not an error
- [ ] Returns \`VolatilityGap\` with: \`instrument\`, \`realized_vol\`, \`implied_vol\`, \`gap\` (= implied_vol - realized_vol), \`computed_at\`
- [ ] Unit tests: known price history → expected realized vol (verify calculation); ATM selection logic; skip conditions
- [ ] \`ruff\`, \`mypy\`, import scan pass

## Agent Notes
Use prompt template: \`docs/prompts/feature_existing_module.md\`
Realized vol formula: stddev(log(P_t / P_{t-1})) × sqrt(252) over the last 30 trading days from DB.
The DB query for price history belongs in \`src/agents/feature_generation/db.py\` (add \`read_price_history()\`), not inline in the agent.

## Depends On
- #6 (market_prices schema)
- #11 (price data in DB from run_ingestion)"

create_issue \
  "Implement compute_sector_dispersion — price spread across XOM, CVX, USO, XLE" \
  "type: feature,phase: 1,agent-assisted" \
  "Phase 1: Core Market Signals & Options" \
  "## Goal
Implement \`compute_sector_dispersion()\` in \`src/agents/feature_generation/feature_generation_agent.py\` to measure price divergence across the four equity/ETF instruments.

## Context
PRD Section 4.3: 'Sector dispersion' is a Phase 1 signal. When XOM and CVX diverge significantly from USO/XLE, it can signal instrument-specific events (e.g. company earnings, sector rotation) vs. broad crude moves. High dispersion combined with a positive volatility gap strengthens the edge score for equity options.

## Acceptance Criteria
- [ ] \`compute_sector_dispersion(market_state: MarketState) -> float | None\` implemented
- [ ] Dispersion computed as the coefficient of variation (CV = stddev / mean) of current prices for XOM, CVX, USO, XLE
- [ ] Returns \`None\` if fewer than 2 of the 4 instruments are present in \`market_state.prices\` — logs a WARNING
- [ ] Returns a normalized float in [0.0, 1.0] (CV capped at 1.0)
- [ ] Unit tests: 4 equal prices → dispersion near 0; 4 prices with one outlier → dispersion > threshold; fewer than 2 instruments → None
- [ ] \`ruff\`, \`mypy\`, import scan pass

## Agent Notes
Use prompt template: \`docs/prompts/feature_existing_module.md\`
CV = stddev(prices) / mean(prices). For 4 instruments the values will typically be in the 0.05–0.30 range. Cap at 1.0 to keep it in the model's [0,1] space.

## Depends On
- #11 (MarketState with real prices)"

create_issue \
  "Implement run_feature_generation — Phase 1 orchestration (volatility gap + sector dispersion)" \
  "type: feature,phase: 1,agent-assisted" \
  "Phase 1: Core Market Signals & Options" \
  "## Goal
Implement \`run_feature_generation()\` in \`src/agents/feature_generation/feature_generation_agent.py\` to orchestrate Phase 1 signal computation and return a populated \`FeatureSet\`.

## Context
Phase 1 activates two signals: volatility gaps and sector dispersion. All other signals (\`futures_curve_steepness\`, \`insider_conviction_score\`, \`narrative_velocity\`, \`supply_shock_probability\`) remain \`None\` in Phase 1 — they are implemented in Phases 2 and 3. The \`events\` parameter is accepted but unused in Phase 1 (\`events=[]\` is passed by the pipeline).

## Acceptance Criteria
- [ ] Calls \`compute_volatility_gap(market_state)\` and \`compute_sector_dispersion(market_state)\` inside separate try/except blocks
- [ ] On individual signal failure: exception appended to \`feature_errors\`; other signals still computed
- [ ] Unimplemented Phase 2/3 signals left as \`None\` with a TODO comment referencing the phase
- [ ] \`FeatureSet\` persisted to DB via \`write_feature_set()\`
- [ ] Structured JSON log at end of cycle: signals computed count, None count, error count, duration_ms
- [ ] Unit tests: full success; one signal fails; all signals fail (still returns FeatureSet, not raises)
- [ ] \`ruff\`, \`mypy\`, import scan pass

## Depends On
- #13 (compute_volatility_gap)
- #14 (compute_sector_dispersion)
- #7 (feature_sets schema)"

create_issue \
  "QA: Feature Generation Agent — integration test and coverage sign-off" \
  "type: qa,type: test,phase: 1" \
  "Phase 1: Core Market Signals & Options" \
  "## Goal
Validate the Feature Generation Agent against a real PostgreSQL instance and confirm Phase 1 signal computation is correct before Strategy Evaluation work begins.

## Context
Feature Generation is the most calculation-intensive module. The volatility gap calculation in particular carries mathematical assumptions (30-day window, log returns, annualization factor) that must be validated against known inputs before they feed into edge scoring.

## Acceptance Criteria

### Integration Tests (testcontainers)
- [ ] \`tests/agents/feature_generation/test_feature_generation_agent_integration.py\` created
- [ ] Test: seed \`market_prices\` with 30 known price records; run \`compute_volatility_gap()\`; assert realized vol within 0.01 of hand-calculated value
- [ ] Test: \`run_feature_generation()\` writes a \`FeatureSet\` row to DB; assert snapshot_time, volatility_gaps (JSONB), sector_dispersion correct
- [ ] Test: partial signal failure → \`feature_errors\` non-empty in DB row

### Golden Dataset Validation
- [ ] Golden scenario documented in test: USO price history with 15% annualized realized vol; USO ATM IV at 22%; expected volatility_gap = +7% (±1%)
- [ ] This scenario drives edge_score > 0.35 in strategy evaluation (forward reference — validate jointly with #19)

### Coverage and Quality
- [ ] \`pytest --cov=src/agents/feature_generation\` shows >80% line coverage
- [ ] Volatility gap math verified by hand-checking one test case
- [ ] \`ruff\`, \`mypy src/agents/feature_generation/\`, import scan pass

## Depends On
- #15 (run_feature_generation implemented)"

echo ""

# ---------------------------------------------------------------------------
# PHASE 1 ISSUES — Strategy Evaluation Agent
# ---------------------------------------------------------------------------
echo "--- Phase 1: Strategy Evaluation Agent ---"

create_issue \
  "Implement compute_edge_score — Phase 1 static heuristic scoring" \
  "type: feature,phase: 1,agent-assisted" \
  "Phase 1: Core Market Signals & Options" \
  "## Goal
Implement \`compute_edge_score()\` in \`src/agents/strategy_evaluation/strategy_evaluation_agent.py\` using a Phase 1 heuristic weighting of volatility gap and sector dispersion signals.

## Context
PRD Section 4.4 and Design Doc Section 5.4: edge score is a composite [0.0–1.0] float. Design Doc Section 10 notes: 'Scoring functions kept simple for initial MVP; complexity added iteratively.' In Phase 1, only two signals are available: volatility_gap and sector_dispersion. The scoring formula should be explicit, commented, and designed so additional signals can be added multiplicatively or additively in later phases without rewriting the function.

## Acceptance Criteria
- [ ] \`compute_edge_score(instrument: str, feature_set: FeatureSet) -> float\` implemented
- [ ] Phase 1 formula: weighted combination of normalized volatility_gap and sector_dispersion
  - volatility_gap contribution: \`clip(gap / 0.20, 0, 1) × 0.70\` (20% IV premium = full weight; 70% of score)
  - sector_dispersion contribution: \`sector_dispersion × 0.30\` (30% of score)
  - If either signal is None: that signal contributes 0.0 (not an error)
- [ ] Formula and weights documented in a block comment with rationale and note: 'Phase 1 heuristic — weights to be tuned in Phase 3 via ML'
- [ ] Returns 0.0 if the instrument has no volatility_gap record in the FeatureSet
- [ ] Unit tests: known FeatureSet inputs → expected edge_score values (3+ test cases covering: high gap + high dispersion, low gap, one signal None)
- [ ] \`ruff\`, \`mypy\`, import scan pass

## Agent Notes
Use prompt template: \`docs/prompts/feature_existing_module.md\`
The scoring formula must be a pure function with no DB access. DB interactions belong in db.py.

## Depends On
- #15 (run_feature_generation producing real FeatureSet)"

create_issue \
  "Implement evaluate_strategies — long straddle, call spread, put spread candidates" \
  "type: feature,phase: 1,agent-assisted" \
  "Phase 1: Core Market Signals & Options" \
  "## Goal
Implement \`evaluate_strategies()\` in \`src/agents/strategy_evaluation/strategy_evaluation_agent.py\` to generate ranked \`StrategyCandidate\` objects for all in-scope instruments and Phase 1 option structures.

## Context
This is the terminal node of the Phase 1 pipeline. Its output matches the PRD Section 9 candidate schema exactly: instrument, structure, expiration, edge_score, signals, generated_at. Calendar spreads are in-scope per PRD Section 3.2 but are not included in Phase 1 strategy generation (PRD Section 10: Phase 1 scope is 'long straddles and call/put spreads').

## Acceptance Criteria
- [ ] Iterates \`INSTRUMENTS_IN_SCOPE\` (USO, XLE, XOM, CVX, CL=F, BZ=F)
- [ ] For each instrument, generates one \`StrategyCandidate\` per structure: \`long_straddle\`, \`call_spread\`, \`put_spread\`
- [ ] \`expiration\` set to 30 (days) for Phase 1 — configurable constant, not hardcoded literal
- [ ] \`edge_score\` computed via \`compute_edge_score(instrument, feature_set)\`
- [ ] \`signals\` dict populated with the contributing signals: \`{'volatility_gap': 'positive'|'negative'|'neutral', 'sector_dispersion': 'high'|'medium'|'low'}\`
- [ ] Candidates with \`edge_score < 0.10\` filtered out (minimum threshold — configurable constant)
- [ ] Returned list sorted by \`edge_score\` descending
- [ ] All candidates persisted to DB via \`write_strategy_candidates()\`
- [ ] \`generated_at\` set to UTC now at time of evaluation
- [ ] Unit tests: known FeatureSet → assert correct number of candidates, correct sort order, schema compliance
- [ ] \`ruff\`, \`mypy\`, import scan pass

## Agent Notes
Use prompt template: \`docs/prompts/feature_existing_module.md\`
The signals dict should use human-readable threshold labels, not raw floats. Define thresholds as module-level constants with comments.

## Depends On
- #7 (strategy_candidates schema)
- #17 (compute_edge_score)"

create_issue \
  "QA: Strategy Evaluation Agent — integration test and coverage sign-off" \
  "type: qa,type: test,phase: 1" \
  "Phase 1: Core Market Signals & Options" \
  "## Goal
Validate the Strategy Evaluation Agent end-to-end with a real PostgreSQL instance, verify the PRD Section 9 output schema is satisfied, and confirm the golden dataset scenario produces expected candidate output.

## Acceptance Criteria

### Integration Tests (testcontainers)
- [ ] \`tests/agents/strategy_evaluation/test_strategy_evaluation_agent_integration.py\` created
- [ ] Test: \`evaluate_strategies()\` with a known FeatureSet writes rows to \`strategy_candidates\`; assert instrument, structure, edge_score, signals fields
- [ ] Test: all candidates in DB have \`edge_score BETWEEN 0 AND 1\`
- [ ] Test: returned list is sorted by edge_score DESC

### Golden Dataset Validation (joint with #16)
- [ ] Golden scenario: USO volatility_gap = +0.07, sector_dispersion = 0.25
  - Expected: USO long_straddle candidate generated with edge_score in [0.38, 0.58]
  - Expected: signals dict contains \`'volatility_gap': 'positive'\`
- [ ] Golden scenario: all signals None → all candidates filtered out (edge_score < threshold)

### Schema Compliance
- [ ] Every \`StrategyCandidate\` returned has all 6 PRD Section 9 fields: instrument, structure, expiration, edge_score, signals, generated_at
- [ ] \`structure\` values are valid \`OptionStructure\` enum members
- [ ] \`generated_at\` is UTC (tzinfo not None)

### Coverage and Quality
- [ ] \`pytest --cov=src/agents/strategy_evaluation\` shows >80% line coverage
- [ ] \`ruff\`, \`mypy src/agents/strategy_evaluation/\`, import scan pass

## Depends On
- #18 (evaluate_strategies implemented)"

echo ""

# ---------------------------------------------------------------------------
# PHASE 1 ISSUES — End-to-End
# ---------------------------------------------------------------------------
echo "--- Phase 1: End-to-End ---"

create_issue \
  "Full pipeline integration test + golden dataset validation" \
  "type: test,type: qa,phase: 1" \
  "Phase 1: Core Market Signals & Options" \
  "## Goal
Implement a full pipeline integration test that runs all four agents in sequence against a real PostgreSQL instance, using a known-good seed dataset, and asserts the final \`StrategyCandidate\` output matches expected values.

## Context
This is the Phase 1 acceptance gate. It validates the complete data flow: seeded market data → Ingestion Agent persists → Feature Generation reads and computes → Strategy Evaluation produces ranked candidates. A passing golden dataset test here means Phase 1 is functionally complete.

## Acceptance Criteria
- [ ] \`tests/pipeline/test_pipeline_integration.py\` created (new \`tests/pipeline/\` directory)
- [ ] Test setup: spin up testcontainers Postgres; apply \`db/schema.sql\`; seed with known market data:
  - USO: 30 daily prices (realistic range), ATM IV at 22%, realized vol ~15%
  - XLE: 30 daily prices, ATM IV at 18%, realized vol ~13%
  - WTI (CL=F): spot price only (no options in Phase 1 for futures)
- [ ] Run \`run_feature_generation(market_state, events=[])\` — assert FeatureSet written to DB
- [ ] Run \`evaluate_strategies(feature_set)\` — assert at least 2 StrategyCandidate rows in DB
- [ ] Assert: USO long_straddle candidate present with edge_score > 0.30
- [ ] Assert: all candidates have complete schema (all 6 PRD Section 9 fields populated)
- [ ] Assert: no runtime import violations (run check_runtime_imports in-process)
- [ ] Test is marked \`@pytest.mark.integration\`
- [ ] Test completes in under 60 seconds

## Notes
This test does NOT test the live API fetches (fetch_crude_prices, etc.) — those require real API keys.
The Ingestion Agent's DB writes are simulated by directly inserting seed data via the test's DB connection.
This is intentional: the pipeline integration test isolates computation correctness from API availability.

## Depends On
- #12 (Ingestion Agent QA complete)
- #16 (Feature Generation QA complete)
- #19 (Strategy Evaluation QA complete)"

create_issue \
  "UAT: Phase 1 end-to-end validation against live market data" \
  "type: uat,phase: 1" \
  "Phase 1: Core Market Signals & Options" \
  "## Goal
Run the complete Phase 1 pipeline against live market data and validate that the output is sensible, explainable, and consistent with observable market conditions.

## Context
The golden dataset test (#20) validates computation correctness on synthetic data. UAT validates the system against reality. This is a human-in-the-loop review: the developer runs the pipeline, reviews the output \`StrategyCandidate\` list, and confirms the recommendations make sense given current market conditions.

## Acceptance Criteria

### Environment
- [ ] Local dev Postgres running (\`docker compose up -d\`)
- [ ] \`.env\` populated with real API keys (ALPHA_VANTAGE_API_KEY, POLYGON_API_KEY or yfinance fallback)
- [ ] \`db/schema.sql\` applied to dev database

### Execution
- [ ] \`run_ingestion()\` completes without error; MarketState contains prices for all 6 instruments
- [ ] \`run_feature_generation()\` produces a FeatureSet with non-None volatility_gaps for at least 2 instruments
- [ ] \`evaluate_strategies()\` returns at least 1 StrategyCandidate with edge_score > 0.10

### Human Review (qualitative)
- [ ] The top-ranked candidate instrument makes intuitive sense given current crude market conditions
- [ ] The \`signals\` dict for each candidate correctly labels volatility_gap as positive/negative/neutral based on current IV vs. recent realized vol
- [ ] No candidate has an implausible edge_score (e.g. 0.99 on a quiet day or 0.00 across all instruments)
- [ ] Ingestion cycle completes in under 60 seconds on local hardware

### Sign-off
- [ ] UAT findings documented as a comment on this issue: top candidate instrument, edge_score, signals map, and assessment of whether the output is reasonable
- [ ] Any anomalies in output are filed as bug issues before Phase 1 is considered complete

## Depends On
- #20 (full pipeline integration test passing)"

create_issue \
  "Phase 1 release: merge develop to main, tag v0.1.0, write release notes" \
  "type: release,phase: 1" \
  "Phase 1: Core Market Signals & Options" \
  "## Goal
Merge the completed Phase 1 develop branch to main, tag the release as v0.1.0, and publish GitHub Release notes documenting what was delivered.

## Context
Per SDLC Section 4.4, merges to main represent production-ready code and require an elevated standard: all CI stages passing, develop stable and tested end-to-end, and a release note added to the GitHub Release.

## Acceptance Criteria

### Pre-merge Checklist
- [ ] All Phase 1 issues (#6–#21) closed
- [ ] \`develop\` branch: all CI stages green (lint, type check, unit tests, integration tests, runtime import check, security scan)
- [ ] Full pipeline integration test (#20) passing on develop
- [ ] UAT (#21) signed off
- [ ] No open bugs filed during UAT with severity > low
- [ ] \`main\` branch is clean and behind develop

### Merge
- [ ] PR opened from \`develop\` to \`main\` — **standard Merge Commit** (not squash — preserves develop history per SDLC Section 4.4)
- [ ] PR description includes: summary of Phase 1 deliverables, CI status confirmation, UAT sign-off reference
- [ ] All CI gates (including security scan) pass on the PR
- [ ] Merge approved and completed

### Tag and Release
- [ ] Git tag \`v0.1.0\` created on the merge commit: \`git tag -a v0.1.0 -m 'Phase 1: Core Market Signals & Options'\`
- [ ] GitHub Release created at \`v0.1.0\` with release notes containing:
  - What was delivered (4 agent stubs → working pipeline, 6 instruments, long straddle + call/put spread candidates)
  - Phase 1 golden dataset baseline: USO long_straddle edge_score range observed in UAT
  - Known limitations: events=[] (Phase 2), no futures curve (Phase 2), no insider signals (Phase 3)
  - Next: Phase 2 planning issue link

### Post-release
- [ ] Phase 2 planning issue opened (see Phase 2 milestone)
- [ ] \`develop\` branch confirmed still active and ready for Phase 2 work

## Depends On
- #21 (UAT signed off)"

echo ""

# ---------------------------------------------------------------------------
# PHASE 2 — Planning placeholder
# ---------------------------------------------------------------------------
echo "--- Phase 2-4: Planning stubs ---"

create_issue \
  "Phase 2 planning: define issues for Supply & Event Augmentation" \
  "type: chore,phase: 2" \
  "Phase 2: Supply & Event Augmentation" \
  "## Goal
Break Phase 2 scope (PRD Section 10) into actionable GitHub Issues before Phase 2 development begins.

## Context
Phase 2 adds: EIA inventory and refinery utilization; event detection via GDELT/NewsAPI; supply disruption indices; event-driven scoring in edge computation.

## To Expand Into Issues
- EIA API integration: weekly inventory and refinery utilization feed
- Implement fetch_news_events (NewsAPI)
- Implement fetch_gdelt_events (GDELT)
- Implement classify_event (keyword heuristic — Phase 2)
- Implement run_event_detection orchestration
- Implement compute_supply_shock_probability (from DetectedEvent list)
- Implement compute_futures_curve_steepness (WTI forward curve — deferred from Phase 1)
- Update compute_edge_score to incorporate supply_shock_probability
- Phase 2 DB schema additions (if any)
- Phase 2 QA: Event Detection integration tests
- Phase 2 UAT: validate event-driven candidates against a known supply event
- Phase 2 release: v0.2.0

## Action
This issue is closed when all Phase 2 issues are created and assigned to the Phase 2 milestone.

## Depends On
- #22 (Phase 1 release complete)"

create_issue \
  "Phase 3 planning: define issues for Alternative / Contextual Signals" \
  "type: chore,phase: 3" \
  "Phase 3: Alternative / Contextual Signals" \
  "## Goal
Break Phase 3 scope (PRD Section 10) into actionable GitHub Issues before Phase 3 development begins.

## Context
Phase 3 adds: insider trades (EDGAR/Quiver), narrative velocity (Reddit/Stocktwits), shipping data (MarineTraffic), cross-sector correlation, full-layer edge scoring with all signals active.

## To Expand Into Issues
- SEC EDGAR insider trade feed
- Quiver Quantitative integration (optional enrichment)
- Narrative velocity: Reddit API for energy subreddits
- Narrative velocity: Stocktwits energy ticker sentiment
- Shipping data: MarineTraffic tanker flow API
- Implement compute_insider_conviction_score
- Implement compute_narrative_velocity
- Implement tanker_disruption_index
- Update compute_edge_score for full Phase 3 signal set
- ML-based weight tuning scaffold (deferred from static heuristic)
- Phase 3 QA and golden dataset update
- Phase 3 UAT
- Phase 3 release: v0.3.0

## Action
This issue is closed when all Phase 3 issues are created and assigned to the Phase 3 milestone.

## Depends On
- Phase 2 release complete"

create_issue \
  "Phase 4 planning: define issues for Optional Enhancements" \
  "type: chore,phase: 4" \
  "Phase 4: Optional Enhancements" \
  "## Goal
Define the scope and issues for Phase 4 optional enhancements when the time comes.

## Context
Phase 4 per PRD Section 10: OPIS or regional refined product pricing (paid data source evaluation required), exotic/multi-legged option structures (iron condors, butterflies), automated execution integration (broker API out of scope for current horizon).

## Notes
Phase 4 is explicitly deferred. This issue exists to capture the milestone and ensure Phase 4 items do not creep into Phases 1-3. Review and refine this scope after Phase 3 UAT.

## Depends On
- Phase 3 release complete"

echo ""
echo "============================================================"
echo "  All labels, milestones, and issues created successfully."
echo ""
echo "  View your project board:"
echo "  https://github.com/${REPO}/issues"
echo ""
echo "  Next step:"
echo "  Close issue #1 by completing the branch protection setup."
echo "  Then begin Phase 0 work starting with issue #2."
echo "============================================================"
echo ""
