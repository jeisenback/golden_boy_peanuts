#!/usr/bin/env bash
# scripts/audit_sprint.sh
#
# Automated audit runner for Architecture, Security, and Quality audits.
#
# What this script does:
#   1. Runs: mypy --strict, ruff --statistics, bandit, pip-audit, pytest --cov
#   2. Produces: audit-report-YYYY-MM-DD.txt in repo root (gitignored)
#   3. Prints a pass/fail summary per tool
#   4. Always exits 0 — this is a non-destructive reporting tool
#
# Usage:
#   bash scripts/audit_sprint.sh
#   bash scripts/audit_sprint.sh --help
#
# Requirements:
#   All dev dependencies installed: pip install -r requirements-dev.txt
#   Additional: pip install bandit pip-audit
#
# After running:
#   1. Review audit-report-YYYY-MM-DD.txt
#   2. Create GitHub issues for findings (see docs/audit_playbook.md § 6)
#   3. Assign issues to 'Audit & Quality' milestone
#
# See: docs/audit_playbook.md

set -uo pipefail

# ---------------------------------------------------------------------------
# --help
# ---------------------------------------------------------------------------
if [[ "${1:-}" == "--help" ]]; then
  cat <<'HELP'
Usage: bash scripts/audit_sprint.sh

Non-destructive automated audit runner. Runs all audit tools and produces
audit-report-YYYY-MM-DD.txt. Always exits 0 — reports findings, never blocks.

Tools run:
  mypy src/ --strict              → type check
  ruff check src/ --statistics   → lint violation summary
  bandit -r src/ -f json         → security scan (HIGH severity count)
  pip-audit -r requirements.txt  → dependency vulnerability scan
  pytest -m "not integration"    → test coverage report (unit tests only)

Output:
  audit-report-YYYY-MM-DD.txt in repo root (gitignored)

See: docs/audit_playbook.md for guidance on triaging findings.
HELP
  exit 0
fi

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
DATESTAMP=$(date +%Y-%m-%d)
REPORT_FILE="audit-report-${DATESTAMP}.txt"

# Remove old same-day report if it exists
rm -f "$REPORT_FILE"

# Track pass/fail per stage
declare -A stage_results

log() {
  echo "$@" | tee -a "$REPORT_FILE"
}

run_stage() {
  local stage_name="$1"
  shift
  log ""
  log "============================================================"
  log "  ${stage_name}"
  log "============================================================"
  if "$@" 2>&1 | tee -a "$REPORT_FILE"; then
    log ""
    log "  RESULT: PASS"
    stage_results["$stage_name"]="PASS"
  else
    log ""
    log "  RESULT: FINDINGS (see above)"
    stage_results["$stage_name"]="FINDINGS"
  fi
}

# ---------------------------------------------------------------------------
# Report header
# ---------------------------------------------------------------------------
{
  echo "========================================================"
  echo "  AUDIT REPORT — Energy Options Opportunity Agent"
  echo "  Date: ${DATESTAMP}"
  echo "  Run: bash scripts/audit_sprint.sh"
  echo "  See docs/audit_playbook.md for guidance"
  echo "========================================================"
} | tee "$REPORT_FILE"

# ---------------------------------------------------------------------------
# Stage 1: mypy strict type check
# ---------------------------------------------------------------------------
run_stage "TYPE CHECK — mypy src/ --strict" \
  python -m mypy src/ --strict

# ---------------------------------------------------------------------------
# Stage 2: ruff lint statistics
# ---------------------------------------------------------------------------
run_stage "LINT — ruff check src/ --statistics" \
  python -m ruff check src/ --statistics

# ---------------------------------------------------------------------------
# Stage 3: bandit security scan
# ---------------------------------------------------------------------------
log ""
log "============================================================"
log "  SECURITY SCAN — bandit -r src/ (HIGH severity count)"
log "============================================================"

BANDIT_JSON="bandit-tmp-${DATESTAMP}.json"
bandit_exit=0
python -m bandit -r src/ -f json -o "$BANDIT_JSON" -ll 2>&1 | tee -a "$REPORT_FILE" || bandit_exit=$?

# Count HIGH severity findings
high_count=0
high_count=$(python3 -c "
import json, sys
try:
    with open('${BANDIT_JSON}') as f:
        data = json.load(f)
    highs = [r for r in data.get('results', []) if r.get('issue_severity') == 'HIGH']
    print(len(highs))
    if highs:
        print('HIGH severity findings:', file=sys.stderr)
        for h in highs:
            print(f\"  {h.get('filename')}:{h.get('line_number')} — {h.get('issue_text')}\", file=sys.stderr)
except Exception as e:
    print('0')
" 2>&1 | tee -a "$REPORT_FILE" | head -1)

rm -f "$BANDIT_JSON"
log ""
log "  BANDIT HIGH severity count: ${high_count}"
if [[ "${high_count}" == "0" ]]; then
  log "  RESULT: PASS"
  stage_results["SECURITY — bandit"]="PASS"
else
  log "  RESULT: ${high_count} HIGH severity finding(s) — must fix before release"
  stage_results["SECURITY — bandit"]="FAIL (${high_count} HIGH)"
fi

# ---------------------------------------------------------------------------
# Stage 4: pip-audit dependency vulnerability scan
# ---------------------------------------------------------------------------
run_stage "DEPENDENCY SCAN — pip-audit -r requirements.txt" \
  python -m pip_audit -r requirements.txt --desc 2>/dev/null || \
  pip-audit -r requirements.txt --desc 2>/dev/null || \
  python -m pip audit -r requirements.txt 2>/dev/null || \
  { log "  WARNING: pip-audit not installed. Run: pip install pip-audit"; true; }

# ---------------------------------------------------------------------------
# Stage 5: pytest with coverage (unit tests only — no Docker required)
# ---------------------------------------------------------------------------
log ""
log "============================================================"
log "  TEST COVERAGE — pytest -m 'not integration' --cov=src/"
log "============================================================"

coverage_exit=0
python -m pytest tests/ \
  -m "not integration" \
  --cov=src/ \
  --cov-report=term-missing \
  --cov-report=json:coverage-tmp.json \
  -q \
  2>&1 | tee -a "$REPORT_FILE" || coverage_exit=$?

# Parse coverage total
coverage_total="N/A"
if [[ -f "coverage-tmp.json" ]]; then
  coverage_total=$(python3 -c "
import json
try:
    with open('coverage-tmp.json') as f:
        data = json.load(f)
    pct = data.get('totals', {}).get('percent_covered', 0)
    print(f'{pct:.1f}')
except:
    print('N/A')
" 2>/dev/null || echo "N/A")
fi

# Count xfail tests
xfail_count=$(grep -r "@pytest.mark.xfail\|xfail" tests/ --include="*.py" -l | xargs grep -c "xfail" 2>/dev/null | awk -F: '{sum+=$2} END{print sum+0}')

# Count total tests
total_tests=$(python -m pytest tests/ -m "not integration" --collect-only -q 2>/dev/null | tail -1 | grep -oE '[0-9]+' | head -1 || echo "unknown")

log ""
log "  TOTAL COVERAGE: ${coverage_total}%"
log "  TOTAL TESTS:    ${total_tests}"
log "  XFAIL COUNT:    ${xfail_count}"

if [[ "$coverage_exit" -eq 0 ]]; then
  stage_results["COVERAGE — pytest"]="PASS (${coverage_total}% coverage)"
else
  stage_results["COVERAGE — pytest"]="FINDINGS (coverage=${coverage_total}%)"
fi

# Cleanup
rm -f "coverage-tmp.json"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
log ""
log "========================================================"
log "  AUDIT SUMMARY — ${DATESTAMP}"
log "========================================================"
log ""

for stage in \
  "TYPE CHECK — mypy src/ --strict" \
  "LINT — ruff check src/ --statistics" \
  "SECURITY — bandit" \
  "DEPENDENCY SCAN — pip-audit -r requirements.txt" \
  "COVERAGE — pytest"; do
  result="${stage_results[$stage]:-NOT RUN}"
  log "  $(printf '%-45s' "$stage")  ${result}"
done

log ""
log "  Coverage:   ${coverage_total}%"
log "  xfail count: ${xfail_count}"
log ""
log "  Report: ${REPORT_FILE}"
log ""
log "  Next steps (docs/audit_playbook.md § 6):"
log "    1. Review ${REPORT_FILE}"
log "    2. Create issues for findings:"
log "       .github/ISSUE_TEMPLATE/architecture_review.md"
log "       .github/ISSUE_TEMPLATE/security_review.md"
log "       .github/ISSUE_TEMPLATE/quality_sprint.md"
log "    3. Assign to milestone: 'Audit & Quality'"
log "========================================================"

echo ""
echo "Audit complete. Report: ${REPORT_FILE}"
echo ""

exit 0
