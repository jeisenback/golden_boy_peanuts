---
name: Security Review
about: Scheduled security audit — bandit, pip-audit, secrets scan, input validation
title: "[SECURITY REVIEW] "
labels: "type: chore"
assignees: ""
---

## Trigger

<!-- What caused this review? Check one: -->
- [ ] Pre-release to staging or production
- [ ] Dependency update (`requirements.txt` changed)
- [ ] New external API integration added to the pipeline
- [ ] Database schema migration performed
- [ ] Quarterly baseline review

## Bandit Findings

<!-- From `bandit -r src/ -f json` (run via `bash scripts/audit_sprint.sh`): -->

**HIGH severity count:** <!-- 0 / N -->

| File | Line | Finding | Severity | Disposition |
|------|------|---------|----------|-------------|
| | | | | |

<!--
Disposition options:
  Fix              — must be fixed before closing this issue
  Suppress         — add # nosec comment with justification in code
  False positive   — document exactly why it is a false positive
-->

## pip-audit Status

<!-- From `pip-audit -r requirements.txt --desc` (run via `bash scripts/audit_sprint.sh`): -->
- [ ] `pip-audit` is clean — no known vulnerabilities
- [ ] Vulnerabilities found: <!-- list package name, CVE ID, severity, plan -->

## Secrets Scan

<!-- Manual check — no hardcoded secrets in src/: -->
- [ ] `grep -rn "api_key\s*=" src/` returns nothing suspicious
- [ ] `grep -rn "password\s*=" src/` returns nothing suspicious
- [ ] `grep -rn "secret\s*=" src/` returns nothing suspicious
- [ ] All API keys and credentials read exclusively from environment variables
- [ ] `.env.example` has an entry for every environment variable referenced in `src/`

## Input Validation Review

<!-- Pydantic at every module boundary (ESOD requirement): -->
- [ ] `ingestion` agent: all external API responses validated through `RawPriceRecord` / `OptionRecord` before use
- [ ] `event_detection` agent: all feed data validated through `DetectedEvent` model
- [ ] `feature_generation` agent: input `MarketState` is a typed and validated Pydantic model
- [ ] `strategy_evaluation` agent: input `FeatureSet` is a typed and validated Pydantic model

## SQL Injection Risk

<!-- No f-string SQL or string formatting in database queries: -->
- [ ] All database queries use parameterized queries or SQLAlchemy ORM (no f-string SQL)
- [ ] `grep -rn 'f".*SELECT\|f".*INSERT\|f".*UPDATE\|f".*DELETE' src/` returns nothing

## retry Coverage

<!-- tenacity required on all external network calls (ESOD requirement): -->
- [ ] All functions that call external APIs are decorated with `@with_retry()` from `src/core/retry.py`
- [ ] No bare `requests.get()`, `requests.post()`, or external client calls without retry

## Acceptance Criteria

- [ ] Bandit report: zero HIGH severity findings (or all suppressed with `# nosec` + documented justification)
- [ ] pip-audit: clean, or all vulnerabilities have tracking fix issues opened with remediation timeline
- [ ] No hardcoded secrets found anywhere in `src/`
- [ ] All external inputs validated via Pydantic at module boundaries
- [ ] No SQL injection risk — parameterized queries confirmed throughout
- [ ] `.env.example` is current and documents every env var used in the codebase
- [ ] All external API calls have tenacity retry applied
- [ ] `bash scripts/audit_sprint.sh` run; security section reviewed; report saved
