#!/usr/bin/env bash
# scripts/sprint_start.sh
#
# Interactive sprint entry gate.
#
# What this script does:
#   1. Validates: on develop branch, clean state, not behind remote
#   2. Gathers: sprint number, sprint goal, milestone name
#   3. Lists open issues in the milestone
#   4. Walks the entry checklist (8 items, y/n each)
#   5. Writes sprint header + issue table to HEARTBEAT.md
#   6. Exits 0 on success, exits 1 if any checklist item fails
#
# Usage:
#   bash scripts/sprint_start.sh
#   bash scripts/sprint_start.sh --help
#
# Requirements: git, gh (GitHub CLI authenticated), run from repo root.
# See: docs/sprint_framework.md § Sprint Entry Checklist

set -uo pipefail

# ---------------------------------------------------------------------------
# --help
# ---------------------------------------------------------------------------
if [[ "${1:-}" == "--help" ]]; then
  cat <<'HELP'
Usage: bash scripts/sprint_start.sh

Interactive sprint entry gate. Validates develop branch state, collects sprint
metadata, walks the Definition of Ready checklist, and writes the sprint header
to HEARTBEAT.md.

Requirements:
  - Run from repo root (HEARTBEAT.md must be present)
  - Must be on the 'develop' branch with a clean working directory
  - gh CLI must be authenticated (gh auth status)

See: docs/sprint_framework.md § 5 (Sprint Entry Checklist)
HELP
  exit 0
fi

# ---------------------------------------------------------------------------
# Dependency checks
# ---------------------------------------------------------------------------
if ! command -v gh &>/dev/null; then
  echo "ERROR: gh (GitHub CLI) is required."
  echo "Install: https://cli.github.com"
  exit 1
fi

if [[ ! -f "HEARTBEAT.md" ]]; then
  echo "ERROR: HEARTBEAT.md not found. Run this script from the repository root."
  exit 1
fi

# ---------------------------------------------------------------------------
# Branch validation
# ---------------------------------------------------------------------------
current_branch=$(git symbolic-ref --short HEAD 2>/dev/null || echo "")
if [[ "$current_branch" != "develop" ]]; then
  echo "ERROR: Must be on 'develop' to start a sprint."
  echo "       Currently on: ${current_branch:-detached HEAD}"
  echo "       Run: git checkout develop"
  exit 1
fi

# ---------------------------------------------------------------------------
# Clean state check
# ---------------------------------------------------------------------------
if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
  echo "ERROR: Working directory has uncommitted changes."
  echo "       Clean up before starting a sprint:"
  git status --short
  exit 1
fi

# ---------------------------------------------------------------------------
# Behind-remote check (warning → offer pull)
# ---------------------------------------------------------------------------
git fetch origin develop --quiet 2>/dev/null || true
behind=$(git log HEAD..origin/develop --oneline 2>/dev/null | wc -l | tr -d ' ')
if [[ "$behind" -gt 0 ]]; then
  echo "WARNING: develop is $behind commit(s) behind origin/develop."
  read -rp "  Pull latest develop before continuing? [Y/n]: " pull_confirm
  if [[ "${pull_confirm:-Y}" != "n" && "${pull_confirm:-Y}" != "N" ]]; then
    git pull origin develop
    echo ""
  fi
fi

# ---------------------------------------------------------------------------
# Sprint metadata prompts
# ---------------------------------------------------------------------------
echo ""
echo "============================================================"
echo "  Sprint Start — Energy Options Opportunity Agent"
echo "============================================================"
echo ""

while true; do
  read -rp "Sprint number (positive integer): " sprint_num
  if [[ "$sprint_num" =~ ^[1-9][0-9]*$ ]]; then
    break
  fi
  echo "  Please enter a positive integer (e.g. 1, 2, 3)."
done

while true; do
  read -rp "Sprint goal (one sentence): " sprint_goal
  if [[ -n "${sprint_goal// /}" ]]; then
    break
  fi
  echo "  Sprint goal cannot be empty."
done

while true; do
  read -rp "GitHub milestone name (exact match): " milestone_name
  if [[ -n "${milestone_name// /}" ]]; then
    break
  fi
  echo "  Milestone name cannot be empty."
done

# ---------------------------------------------------------------------------
# List open issues in milestone
# ---------------------------------------------------------------------------
echo ""
echo "=== Open issues in milestone: '$milestone_name' ==="
echo ""
gh issue list \
  --milestone "$milestone_name" \
  --state open \
  --json number,title,labels \
  --jq '.[] | "  #\(.number)  [\(.labels | map(.name) | join(", "))]  \(.title)"' \
  2>/dev/null || echo "  (Could not fetch issues — check milestone name and gh auth)"
echo ""

# ---------------------------------------------------------------------------
# Entry checklist (8 items — exit 1 on any 'n')
# ---------------------------------------------------------------------------
echo "=== Sprint Entry Checklist (docs/sprint_framework.md § 5) ==="
echo "    Answer y/n for each item. Any 'n' will prevent the sprint from starting."
echo ""

checklist_items=(
  "Current branch is 'develop' and working directory is clean"
  "develop is current with origin/develop (not behind remote)"
  "Sprint number, goal, and milestone are confirmed above"
  "All sprint issues listed above have milestone and type/phase labels set"
  "All sprint issues meet Definition of Ready (docs/sprint_framework.md § 3)"
  "No issues in this sprint have the 'blocked' label"
  "CI is currently green on develop (check: https://github.com/jeisenback/golden_boy_peanuts/actions)"
  "Sprint goal is agreed and clearly stated above"
)

failed_items=()
for item in "${checklist_items[@]}"; do
  while true; do
    read -rp "  [ ] $item [y/n]: " answer
    case "${answer,,}" in
      y|yes) echo "      ✓"; break ;;
      n|no)  echo "      ✗ — FAILED"; failed_items+=("$item"); break ;;
      *)     echo "      Please enter y or n." ;;
    esac
  done
done

echo ""

if [[ "${#failed_items[@]}" -gt 0 ]]; then
  echo "============================================================"
  echo "  SPRINT NOT STARTED — ${#failed_items[@]} checklist item(s) failed:"
  echo ""
  for item in "${failed_items[@]}"; do
    echo "  ✗  $item"
  done
  echo ""
  echo "  Resolve the items above, then re-run: bash scripts/sprint_start.sh"
  echo "============================================================"
  exit 1
fi

# ---------------------------------------------------------------------------
# Compute dates (portable: Linux + macOS)
# ---------------------------------------------------------------------------
start_date=$(date +%Y-%m-%d)
target_date=$(date -d "+7 days" +%Y-%m-%d 2>/dev/null \
  || date -v +7d +%Y-%m-%d 2>/dev/null \
  || echo "YYYY-MM-DD")

# ---------------------------------------------------------------------------
# Fetch sprint issues for the table
# ---------------------------------------------------------------------------
issues_table=$(gh issue list \
  --milestone "$milestone_name" \
  --state open \
  --json number,title \
  --jq '.[] | "| \(.number) | \(.title) | Not Started | — | — |"' \
  2>/dev/null || echo "| — | Could not fetch issues | — | — | — |")

# ---------------------------------------------------------------------------
# Write sprint header to HEARTBEAT.md (temp file + mv for safety)
# ---------------------------------------------------------------------------
tmp=$(mktemp)

# Write the new sprint block at the top, preserve existing retro/history below
{
  cat <<SPRINT_BLOCK
# HEARTBEAT.md — Energy Options Opportunity Agent
# -----------------------------------------------------------------------
# COMMITTED. Always current. If this file is stale, it is wrong.
#
# Claude Code: READ THIS FILE BEFORE DOING ANYTHING ELSE EACH SESSION.
# It tells you what sprint is active, what you are working on, and
# what branch to use. If you skip this step, you will work on the wrong thing.
#
# Update protocol: see bottom of this file.
# -----------------------------------------------------------------------

## Current Sprint

| Field | Value |
|-------|-------|
| Sprint Number | ${sprint_num} |
| Sprint Name | Sprint ${sprint_num} — ${milestone_name}: ${sprint_goal} |
| Goal | ${sprint_goal} |
| Start Date | ${start_date} |
| Target Close | ${target_date} |
| Status | ACTIVE |

## Sprint Issues

| # | Title | Status | Branch | Notes |
|---|-------|--------|--------|-------|
${issues_table}

## Current Active Branch

\`develop\` — no active feature branch yet; create branches per issue via \`bash scripts/new_branch.sh\`

## Blockers

- None

## Last Merged PR

- None yet this sprint

---

SPRINT_BLOCK

  # Append existing history from previous HEARTBEAT (skip old header + Current Sprint section)
  # Look for the first line starting with "## Sprint " or "## Sprint 0" (history section)
  awk '/^---$/{found++} found>=1{print}' HEARTBEAT.md | tail -n +2

} > "$tmp"

mv "$tmp" HEARTBEAT.md

# ---------------------------------------------------------------------------
# Print completion message
# ---------------------------------------------------------------------------
echo "============================================================"
echo "  Sprint ${sprint_num} Started"
echo ""
echo "  Goal:      ${sprint_goal}"
echo "  Milestone: ${milestone_name}"
echo "  Start:     ${start_date}"
echo "  Target:    ${target_date}"
echo ""
echo "  HEARTBEAT.md updated with sprint header and issue table."
echo ""
echo "  Next steps:"
echo "    1. Create a branch per issue:  bash scripts/new_branch.sh"
echo "    2. Update SESSION.md at the start of each session"
echo "    3. Update HEARTBEAT.md issue row when status changes"
echo "    4. Close sprint when done:     bash scripts/sprint_close.sh"
echo "============================================================"
