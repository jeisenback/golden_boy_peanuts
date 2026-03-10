#!/usr/bin/env bash
# post_session.sh
#
# Runs automated post-session quality checks, then prints the ADLC
# post-session checklist (Section 7.3).
# Run this immediately after every Claude Code or Cursor agent session.
#
# Automated steps (fail fast):
#   1. git diff --stat            — warns on unstaged/untracked changes
#   2. check_runtime_imports.py   — no langchain.* in src/
#   3. scripts/local_check.sh     — ruff, black, mypy, import scan
#
# Exits non-zero if any automated step fails.
# Idempotent — safe to run multiple times.
#
# Usage: bash scripts/post_session.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

fail() {
  echo ""
  echo "Post-session check failed at: $1. Fix before committing."
  echo ""
  exit 1
}

echo ""
echo "============================================================"
echo "  ADLC Post-Session Checks  (automated)"
echo "============================================================"
echo ""

# Preflight: verify we are inside a git work tree with a valid HEAD
if ! git -C "${REPO_ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  fail "git preflight: not inside a git work tree"
fi
if ! git -C "${REPO_ROOT}" rev-parse --verify HEAD >/dev/null 2>&1; then
  fail "git preflight: no valid HEAD commit found"
fi

# Step 1: unstaged/untracked changes warning
echo "  [1/3] Checking for unstaged/untracked changes..."
git -C "${REPO_ROOT}" diff --stat --
if ! git -C "${REPO_ROOT}" diff --quiet -- || [ -n "$(git -C "${REPO_ROOT}" ls-files --others --exclude-standard)" ]; then
  echo ""
  echo "  Working tree has unstaged or untracked changes."
  echo "  Review the diff above (and any untracked files), then commit or stash before proceeding."
  fail "unstaged or untracked changes in working tree"
fi
echo ""

# Step 2: runtime import scan
echo "  [2/3] Running runtime import scan..."
if ! (cd "${REPO_ROOT}" && python ".github/scripts/check_runtime_imports.py"); then
  fail "check_runtime_imports.py"
fi
echo ""

# Step 3: local quality gate (ruff, black, mypy, import scan)
echo "  [3/3] Running local quality gate — ruff, black, mypy, import scan (local_check.sh)..."
if ! (cd "${REPO_ROOT}" && bash "scripts/local_check.sh"); then
  fail "local_check.sh"
fi
echo ""

echo "  All automated checks passed."
echo ""

echo "============================================================"
echo "  ADLC Post-Session Checklist  (Section 7.3)"
echo "============================================================"
echo ""
echo "  1. GIT DIFF REVIEW"
echo "     Run: git diff"
echo "     Read every changed line before running any tests."
echo "     Understand what the agent built."
echo ""
echo "  2. REMOVE NOISE"
echo "     [ ] Remove debug print statements"
echo "     [ ] Remove commented-out code (alternatives the agent tried)"
echo "     [ ] Remove unused imports"
echo "     [ ] Remove leftover stubs not tied to a TODO comment"
echo ""
echo "  3. VERIFY QUALITY"
echo "     [ ] All new public functions have type hints"
echo "     [ ] All new public functions have docstrings"
echo "     [ ] No bare 'except:' or 'except Exception:' without logging"
echo ""
echo "  4. RUNTIME IMPORT SCAN"
echo "     Run: python .github/scripts/check_runtime_imports.py"
echo "     Must exit 0 before pushing."
echo ""
echo "  5. FULL LOCAL CHECK"
echo "     Run: bash scripts/local_check.sh"
echo "     All stages (ruff, black, mypy, import scan) must PASS."
echo ""
echo "  6. CLEANUP COMMIT"
echo "     After cleanup, commit separately from agent output:"
echo "     git commit -m 'chore: post-session cleanup for #<issue>'"
echo ""
echo "  7. READY TO PUSH?"
echo "     [ ] git diff reviewed line-by-line"
echo "     [ ] Debug noise removed"
echo "     [ ] Type hints and docstrings verified"
echo "     [ ] scripts/local_check.sh exits 0"
echo "     [ ] Cleanup commit made"
echo ""
echo "  Then: open PR to develop. Apply 'needs-review' label."
echo "  Pause. Review the PR as a second developer would."
echo ""
echo "============================================================"
echo ""
