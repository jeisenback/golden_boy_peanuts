#!/usr/bin/env bash
# scripts/sprint_close.sh
#
# Sprint exit gate.
#
# What this script does:
#   1. Reads current sprint number and milestone from HEARTBEAT.md
#   2. Lists open issues in the sprint milestone (warning, not hard fail)
#   3. Prompts for retrospective notes (3 questions)
#   4. Walks exit checklist (hard fail on "CI not green"; others are warnings)
#   5. Appends sprint summary + retro block to HEARTBEAT.md
#   6. Optionally chains to sprint_start.sh for next sprint
#
# Usage:
#   bash scripts/sprint_close.sh
#   bash scripts/sprint_close.sh --help
#
# Requirements: git, gh (GitHub CLI authenticated), run from repo root.
# See: docs/sprint_framework.md § Sprint Exit Checklist

set -uo pipefail

# ---------------------------------------------------------------------------
# --help
# ---------------------------------------------------------------------------
if [[ "${1:-}" == "--help" ]]; then
  cat <<'HELP'
Usage: bash scripts/sprint_close.sh

Sprint exit gate. Lists open issues, captures retrospective notes, writes
sprint summary to HEARTBEAT.md, and optionally starts the next sprint.

Requirements:
  - Run from repo root (HEARTBEAT.md must be present with active sprint data)
  - gh CLI must be authenticated

Hard fail condition: CI is not green on develop.
See: docs/sprint_framework.md § 6 (Sprint Exit Checklist)
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
# Read current sprint info from HEARTBEAT.md
# ---------------------------------------------------------------------------
sprint_num=$(grep "| Sprint Number |" HEARTBEAT.md | head -1 | awk -F'|' '{print $3}' | tr -d ' ')
sprint_name=$(grep "| Sprint Name |" HEARTBEAT.md | head -1 | awk -F'|' '{print $3}' | sed 's/^ *//' | sed 's/ *$//')
sprint_goal=$(grep "| Goal |" HEARTBEAT.md | head -1 | awk -F'|' '{print $3}' | sed 's/^ *//' | sed 's/ *$//')
start_date=$(grep "| Start Date |" HEARTBEAT.md | head -1 | awk -F'|' '{print $3}' | tr -d ' ')

# Extract milestone name: "Sprint N — MilestoneName: goal" → "MilestoneName"
milestone_name=$(echo "$sprint_name" | sed 's/Sprint [0-9]* — //' | awk -F':' '{print $1}' | sed 's/^ *//' | sed 's/ *$//')

if [[ -z "$sprint_num" || "$sprint_num" == "0" ]]; then
  echo "WARNING: Could not read sprint number from HEARTBEAT.md."
  read -rp "Enter sprint number manually: " sprint_num
fi

echo ""
echo "============================================================"
echo "  Sprint Close — Sprint ${sprint_num}"
if [[ -n "$sprint_name" ]]; then
  echo "  ${sprint_name}"
fi
echo "============================================================"
echo ""

# ---------------------------------------------------------------------------
# List open issues in sprint milestone
# ---------------------------------------------------------------------------
echo "=== Checking open issues in milestone: '${milestone_name}' ==="
echo ""

open_count=0
if [[ -n "$milestone_name" ]]; then
  open_count=$(gh issue list \
    --milestone "$milestone_name" \
    --state open \
    --json number \
    --jq '. | length' 2>/dev/null || echo "0")

  if [[ "$open_count" -gt 0 ]]; then
    echo "WARNING: $open_count issue(s) still open in this sprint:"
    echo ""
    gh issue list \
      --milestone "$milestone_name" \
      --state open \
      --json number,title \
      --jq '.[] | "  #\(.number)  \(.title)"' 2>/dev/null || true
    echo ""
    echo "  These will be recorded as carry-overs in HEARTBEAT.md."
    echo "  You may still close the sprint; carry-overs move to the next sprint backlog."
  else
    echo "  All sprint issues are closed."
  fi
else
  echo "  (Could not determine milestone name — skipping open issue check)"
fi

echo ""

# ---------------------------------------------------------------------------
# Retrospective (3 prompts)
# ---------------------------------------------------------------------------
echo "=== Sprint Retrospective ==="
echo "    (Notes will be appended to HEARTBEAT.md)"
echo ""
read -rp "  What went well this sprint? " retro_well
read -rp "  What was slow or blocked? " retro_slow
read -rp "  What will we change next sprint? " retro_change
echo ""

# ---------------------------------------------------------------------------
# Exit checklist
# ---------------------------------------------------------------------------
echo "=== Sprint Exit Checklist (docs/sprint_framework.md § 6) ==="
echo ""

exit_warnings=()
ci_failed=false

# Item 1: CI green — HARD FAIL if 'n'
while true; do
  read -rp "  [ ] CI is currently green on develop? [y/n]: " ci_answer
  case "${ci_answer,,}" in
    y|yes) echo "      ✓"; break ;;
    n|no)
      echo ""
      echo "  ============================================================"
      echo "  HARD FAIL: Do not close sprint until develop CI is green."
      echo "  Investigate the CI failure, fix it, then re-run this script."
      echo "  Check CI: https://github.com/jeisenback/golden_boy_peanuts/actions"
      echo "  ============================================================"
      ci_failed=true
      break
      ;;
    *) echo "      Please enter y or n." ;;
  esac
done

if [[ "$ci_failed" == "true" ]]; then
  exit 1
fi

# Items 2-4: warnings, not hard fails
soft_items=(
  "All closed sprint issues have a comment: 'Closing: all AC verified, merged in PR #N'"
  "HEARTBEAT.md is current (session notes from this sprint are present)"
  "Carry-over issues have been moved to next sprint backlog or marked 'blocked'"
)

for item in "${soft_items[@]}"; do
  while true; do
    read -rp "  [ ] $item [y/n]: " answer
    case "${answer,,}" in
      y|yes) echo "      ✓"; break ;;
      n|no)  echo "      ⚠ WARNING — noted"; exit_warnings+=("$item"); break ;;
      *)     echo "      Please enter y or n." ;;
    esac
  done
done

echo ""

# ---------------------------------------------------------------------------
# Compute close date and carry-overs
# ---------------------------------------------------------------------------
close_date=$(date +%Y-%m-%d)
closed_count=$(gh issue list \
  --milestone "$milestone_name" \
  --state closed \
  --json number \
  --jq '. | length' 2>/dev/null || echo "unknown")

carryover_list=""
if [[ "$open_count" -gt 0 ]]; then
  carryover_list=$(gh issue list \
    --milestone "$milestone_name" \
    --state open \
    --json number \
    --jq '[.[].number] | join(", #")' 2>/dev/null || echo "see GitHub")
  carryover_list="#${carryover_list}"
else
  carryover_list="None"
fi

# ---------------------------------------------------------------------------
# Append sprint summary + retro to HEARTBEAT.md (temp file + mv)
# ---------------------------------------------------------------------------
tmp=$(mktemp)

# Write existing HEARTBEAT content, then append new sprint summary
{
  cat HEARTBEAT.md
  cat <<RETRO_BLOCK

---

## Sprint ${sprint_num} Summary — Closed ${close_date}

| Field | Value |
|-------|-------|
| Goal | ${sprint_goal} |
| Start | ${start_date} |
| Closed | ${close_date} |
| Issues Closed | ${closed_count} |
| Carry-overs | ${carryover_list} |

### Sprint ${sprint_num} Retro Notes

| | |
|---|---|
| What went well | ${retro_well} |
| What was slow | ${retro_slow} |
| What to change | ${retro_change} |

RETRO_BLOCK
} > "$tmp"

mv "$tmp" HEARTBEAT.md

# ---------------------------------------------------------------------------
# Print summary
# ---------------------------------------------------------------------------
echo "============================================================"
echo "  Sprint ${sprint_num} Closed — ${close_date}"
echo ""
echo "  Issues closed:   ${closed_count}"
echo "  Carry-overs:     ${carryover_list}"
if [[ "${#exit_warnings[@]}" -gt 0 ]]; then
  echo ""
  echo "  Warnings (action needed):"
  for w in "${exit_warnings[@]}"; do
    echo "    ⚠ $w"
  done
fi
echo ""
echo "  HEARTBEAT.md updated with sprint summary and retro notes."
echo "============================================================"
echo ""

# ---------------------------------------------------------------------------
# Offer to start next sprint
# ---------------------------------------------------------------------------
read -rp "Start next sprint now? [y/N]: " next_sprint
if [[ "${next_sprint,,}" == "y" || "${next_sprint,,}" == "yes" ]]; then
  echo ""
  bash scripts/sprint_start.sh
fi
