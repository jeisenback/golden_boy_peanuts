#!/usr/bin/env bash
# local_check.sh
#
# Runs the full local quality gate before pushing a branch.
# Mirrors the CI pipeline stages: ruff, black, mypy, runtime import scan.
#
# Exits 0 only if ALL stages pass.
# Exits 1 if any stage fails (with a clear summary).
#
# Usage: bash scripts/local_check.sh
# Requirements: ruff, black, mypy, python >= 3.11 — all in active venv

set -uo pipefail

results=()

run_stage() {
  local stage_name="$1"
  shift
  echo ""
  echo "--- ${stage_name} ---"
  if "$@"; then
    results+=("PASS  ${stage_name}")
  else
    results+=("FAIL  ${stage_name}")
  fi
}

echo ""
echo "=== Local Quality Gate (mirrors CI) ==="
echo ""

# Stage 1: ruff lint
run_stage "ruff lint" ruff check src/ tests/

# Stage 2: black format check
run_stage "black format check" black --check src/ tests/

# Stage 3: mypy strict type check
run_stage "mypy (strict)" mypy src/

# Stage 4: runtime import scan (the ESOD architectural rule enforcer)
run_stage "runtime import scan" python .github/scripts/check_runtime_imports.py

# --- Summary ---
echo ""
echo "=== Results ==="
any_fail=0
for result in "${results[@]}"; do
  echo "  ${result}"
  if [[ "${result}" == FAIL* ]]; then
    any_fail=1
  fi
done

echo ""
if [[ $any_fail -eq 0 ]]; then
  echo "ALL STAGES PASSED. Safe to push."
  exit 0
else
  echo "ONE OR MORE STAGES FAILED. Fix all issues before pushing."
  echo "(SDLC Section 4.2: do not push a failing branch)"
  exit 1
fi
