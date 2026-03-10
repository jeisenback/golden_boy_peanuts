# Audit Playbook — Energy Options Opportunity Agent
#
# Audit is a sprint, not an afterthought.
# It has its own milestone, issue templates, entry/exit criteria, and the same
# ADLC loop as any other sprint. The difference is output: issues, not features.
#
# Script: scripts/audit_sprint.sh
# Issue templates: .github/ISSUE_TEMPLATE/architecture_review.md
#                  .github/ISSUE_TEMPLATE/security_review.md
#                  .github/ISSUE_TEMPLATE/quality_sprint.md

## 1. Audit Philosophy

An audit sprint produces:
- A timestamped `audit-report-YYYY-MM-DD.txt` (gitignored; local reference and review artifact)
- One or more GitHub issues in the "Audit & Quality" milestone documenting findings
- A clear pass/fail state for each audit dimension

Audit issues are treated as regular work items: they go through DoR, DoD, and the full
10-step ADLC loop. An "audit finding" that is never tracked in a GitHub issue is not an audit finding.

---

## 2. Audit & Quality Milestone Setup

Create once. All audit-generated issues go to this milestone. No due date.

```bash
# Check if milestone already exists first
existing=$(gh api repos/jeisenback/golden_boy_peanuts/milestones \
  --jq '.[] | select(.title == "Audit & Quality") | .number' 2>/dev/null)

if [[ -z "$existing" ]]; then
  gh api repos/jeisenback/golden_boy_peanuts/milestones \
    --method POST \
    --field title="Audit & Quality" \
    --field description="Issues generated from architecture, security, and quality audit sprints. No due date." \
    --field state="open"
  echo "Audit & Quality milestone created."
else
  echo "Audit & Quality milestone already exists (#$existing). Skipping creation."
fi
```

Verify:
```bash
gh api repos/jeisenback/golden_boy_peanuts/milestones --jq '.[].title'
```

---

## 3. Audit Mode 1: Architecture Review

### When to Run (any one trigger is sufficient)
- Before any major phase transition (Phase 1→2, Phase 2→3, etc.)
- New agent or team member joins (including adding a new AI coding tool)
- Quarterly baseline (every 13 weeks, regardless of phase progress)
- Human lead decides module boundaries feel unclear or have drifted

### What to Check

```
[ ] Module boundaries respected:
    - src/agents/ingestion/ imports only from src/core/ and its own package
    - src/agents/event_detection/ imports only from src/core/ and its own package
    - src/agents/feature_generation/ imports only from src/core/ and its own package
    - src/agents/strategy_evaluation/ imports only from src/core/ and its own package
    - No agent imports from a downstream agent in the pipeline

[ ] No circular imports
    Verify: python -c "import src.agents.ingestion; import src.agents.event_detection; ..."

[ ] ESOD compliance — import scanner is clean
    Verify: python .github/scripts/check_runtime_imports.py

[ ] Dependency review — every package in requirements.txt is actively used in src/

[ ] Schema review — all time-series tables use TIMESTAMPTZ (not TIMESTAMP)
    and schema supports future `SELECT create_hypertable(...)` without SQL changes

[ ] LLM wrapper integrity — all LLM calls route through src/core/llm_wrapper.py
    Verify: grep -rn "openai\.\|anthropic\.\|ChatOpenAI\|Claude(" src/ returns nothing unexpected

[ ] Public API review — no function signatures changed without updating all callers
```

### Issue Template
`.github/ISSUE_TEMPLATE/architecture_review.md`
Labels: `type: chore`, `phase: [current]`
Milestone: `Audit & Quality`

### Output from `audit_sprint.sh`
Architecture section of `audit-report-YYYY-MM-DD.txt`:
- Import scan result (PASS / FAIL with violation list)
- mypy strict result

---

## 4. Audit Mode 2: Security Sprint

### When to Run (any one trigger is sufficient)
- Before any deployment to staging or production
- After any change to `requirements.txt` (dependency update)
- After any new external API integration is added to the pipeline
- After any database schema migration
- Quarterly baseline

### What to Check

```
[ ] bandit -r src/ report: zero HIGH severity findings
    (MEDIUM findings: triage; document any False Positives with # nosec)

[ ] pip-audit -r requirements.txt: clean output (no known vulnerabilities)
    (Known acceptable: document with CVE number and remediation timeline)

[ ] No hardcoded secrets:
    grep -rn "api_key\s*=\s*['\"]" src/ -- returns nothing suspicious
    grep -rn "password\s*=\s*['\"]" src/ -- returns nothing suspicious
    grep -rn "secret\s*=\s*['\"]" src/  -- returns nothing suspicious

[ ] All external inputs validated via Pydantic at module boundaries
    - Ingestion: all API responses validated through RawPriceRecord / OptionRecord
    - Event Detection: all feed data validated through DetectedEvent
    - Feature Generation: input MarketState is a typed Pydantic model
    - Strategy Evaluation: input FeatureSet is a typed Pydantic model

[ ] No SQL injection risk:
    grep -rn 'f".*SELECT\|f".*INSERT\|f".*UPDATE\|f".*DELETE' src/ -- returns nothing
    All DB queries use parameterized queries or ORM only

[ ] Environment variables documented:
    .env.example has an entry for every environment variable used in src/
    grep -rn "os.environ\|os.getenv" src/ -- cross-check each against .env.example

[ ] tenacity applied to all external network calls in src/
    grep -rn "requests.get\|requests.post\|httpx\." src/ -- each should have @with_retry() or @retry()
```

### Issue Template
`.github/ISSUE_TEMPLATE/security_review.md`
Labels: `type: chore`, `phase: [current]`
Milestone: `Audit & Quality`

### Output from `audit_sprint.sh`
Security section of `audit-report-YYYY-MM-DD.txt`:
- bandit HIGH severity count and finding list
- pip-audit status (clean / vulnerabilities found)

---

## 5. Audit Mode 3: Quality Sprint

### When to Run (any one trigger is sufficient)
- Test coverage drops below 80% for any agent module
- 3 or more consecutive feature sprints without a quality checkpoint
- Before any Phase UAT (user acceptance testing) milestone
- xfail count is not decreasing sprint-over-sprint (stale stubs)
- Human lead decides technical debt is accumulating

### What to Check

```
[ ] Coverage report: which modules are below the 80% target?
    pytest --cov=src/ --cov-report=term-missing -m "not integration"
    List each module below 80% with current coverage %

[ ] xfail ratio: how many xfail tests vs. total?
    pytest tests/ -v --tb=no | grep -c XFAIL
    Each remaining xfail must have: a linked GitHub issue OR a documented reason

[ ] ruff violations: no violation type with more than 5 occurrences
    ruff check src/ --statistics
    Any type with >5 occurrences should have a fix issue opened

[ ] mypy errors: mypy src/ --strict exits 0
    Any errors in recently added modules are a quality failure

[ ] Tech debt: any TODO comments older than 2 sprints without a tracking issue?
    grep -rn "# TODO" src/ -- each should reference a GitHub issue: # TODO (#N)

[ ] Test isolation: do any tests fail when run in a different order?
    pytest tests/ --randomly (if pytest-randomly is installed)

[ ] Dead code: any functions defined but never called or tested?
    (manual review of recently added modules)
```

### Issue Template
`.github/ISSUE_TEMPLATE/quality_sprint.md`
Labels: `type: test`, `phase: [current]`
Milestone: `Audit & Quality`

### Output from `audit_sprint.sh`
Quality section of `audit-report-YYYY-MM-DD.txt`:
- Coverage % per agent module
- xfail count
- ruff violation statistics summary
- Total test count

---

## 6. Running an Audit

```bash
# Step 1: Run the automated audit script
bash scripts/audit_sprint.sh
# Produces: audit-report-YYYY-MM-DD.txt in repo root (gitignored)
# Exits 0 always — non-destructive, reports everything

# Step 2: Review the report
# Open audit-report-YYYY-MM-DD.txt in your editor

# Step 3: For each failing check, create a GitHub issue
gh issue create \
  --template architecture_review.md \   # or security_review.md or quality_sprint.md
  --title "[ARCH REVIEW] Module boundary violation — ingestion imports feature_generation" \
  --milestone "Audit & Quality"

# Step 4: Prioritize findings
# HIGH bandit findings: fix before next release
# Zero-coverage modules: schedule in next quality sprint
# pip-audit vulnerabilities: triage within 1 sprint of discovery
```

---

## 7. Audit Entry and Exit Criteria

### Audit Sprint Entry
Same as feature sprint entry (see `docs/sprint_framework.md` § 5), plus:
- `bash scripts/audit_sprint.sh` has been run today and `audit-report-YYYY-MM-DD.txt` exists
- At least one issue created in `Audit & Quality` milestone from the report findings

### Audit Sprint Done
- All acceptance criteria in the audit issue(s) are checked
- An updated `bash scripts/audit_sprint.sh` run shows improvement vs. the baseline report
- Any HIGH bandit severity findings: resolved or have documented `# nosec` with justification
- Coverage report shows improvement (if quality sprint: all targeted modules at ≥80%)
- All new audit issues created for remaining findings have been triaged and milestoned
