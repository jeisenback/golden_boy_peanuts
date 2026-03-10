#!/usr/bin/env bash
# scripts/refine_issue.sh
#
# Pre-sprint issue refinement helper.
#
# What this script does:
#   1. Displays the full GitHub issue
#   2. Walks the Definition of Ready checklist (7 items, y/n/skip)
#   3. Can add labels: 'blocked', 'agent-assisted'
#   4. Removes 'needs-review' label when all DoR items pass (signals Ready)
#   5. Prints READY or NOT READY summary
#
# Usage:
#   bash scripts/refine_issue.sh <issue_number>
#   bash scripts/refine_issue.sh 8
#   bash scripts/refine_issue.sh --help
#
# Requirements: gh CLI authenticated.
# See: docs/sprint_framework.md § 3 (Definition of Ready)

set -uo pipefail

# ---------------------------------------------------------------------------
# --help and argument validation
# ---------------------------------------------------------------------------
if [[ "${1:-}" == "--help" || -z "${1:-}" ]]; then
  cat <<'HELP'
Usage: bash scripts/refine_issue.sh <issue_number>

Walks the Definition of Ready checklist for a single GitHub issue.
Can add 'blocked' or 'agent-assisted' labels, and removes 'needs-review'
when all DoR criteria are met (signaling the issue is Ready for a sprint).

Example:
  bash scripts/refine_issue.sh 8

Definition of Ready: docs/sprint_framework.md § 3
HELP
  exit 0
fi

issue_num="$1"
if ! [[ "$issue_num" =~ ^[0-9]+$ ]]; then
  echo "ERROR: Argument must be a numeric issue number. Got: $issue_num"
  echo "Usage: bash scripts/refine_issue.sh <issue_number>"
  exit 1
fi

# ---------------------------------------------------------------------------
# Dependency check
# ---------------------------------------------------------------------------
if ! command -v gh &>/dev/null; then
  echo "ERROR: gh (GitHub CLI) is required."
  echo "Install: https://cli.github.com"
  exit 1
fi

# ---------------------------------------------------------------------------
# Display issue
# ---------------------------------------------------------------------------
echo ""
echo "============================================================"
echo "  Issue #${issue_num} — Refinement Review"
echo "============================================================"
echo ""
gh issue view "$issue_num" 2>/dev/null || {
  echo "ERROR: Could not fetch issue #${issue_num}. Check issue number and gh auth."
  exit 1
}
echo ""

# ---------------------------------------------------------------------------
# Definition of Ready checklist (7 items — must match working_agreement.md § 3 exactly)
# ---------------------------------------------------------------------------
echo "=== Definition of Ready Checklist (docs/sprint_framework.md § 3) ==="
echo "    Answer y (pass) / n (fail) / s (skip/already confirmed)"
echo ""

dor_items=(
  "Has a clear, single-sentence goal stating what 'done' looks like"
  "Has at least 3 specific, testable acceptance criteria (checkboxes in issue body)"
  "Milestone assigned (Phase 0 / 1 / 2 / 3 / 4 / Audit & Quality)"
  "Labels set: type:* AND (phase:* or audit) — both required"
  "No 'blocked' label on the issue"
  "Depends-on issues are closed, or explicitly noted as unblocked with justification in the body"
  "Reviewed and approved for this sprint by the human lead"
)

failed_count=0
passed_count=0
skipped_count=0

for item in "${dor_items[@]}"; do
  while true; do
    read -rp "  [ ] $item [y/n/s]: " answer
    case "${answer,,}" in
      y|yes)
        echo "      ✓"
        ((passed_count++)) || true
        break
        ;;
      n|no)
        echo "      ✗ — NOT MET"
        ((failed_count++)) || true
        break
        ;;
      s|skip)
        echo "      ↷ skipped"
        ((skipped_count++)) || true
        break
        ;;
      *)
        echo "      Please enter y (pass), n (fail), or s (skip)."
        ;;
    esac
  done
done

echo ""

# ---------------------------------------------------------------------------
# Label actions
# ---------------------------------------------------------------------------
# Ask about 'blocked' label
read -rp "Mark issue #${issue_num} as 'blocked'? [y/N]: " mark_blocked
if [[ "${mark_blocked,,}" == "y" || "${mark_blocked,,}" == "yes" ]]; then
  gh issue edit "$issue_num" --add-label "blocked" 2>/dev/null && echo "  Added label: blocked" || \
    echo "  WARNING: Could not add 'blocked' label (may not exist — run create_issues.sh)"
fi

# Ask about 'agent-assisted' label
read -rp "Will this be agent-assisted (Claude Code / Cursor / Copilot)? [y/N]: " mark_agent
if [[ "${mark_agent,,}" == "y" || "${mark_agent,,}" == "yes" ]]; then
  gh issue edit "$issue_num" --add-label "agent-assisted" 2>/dev/null && echo "  Added label: agent-assisted" || \
    echo "  WARNING: Could not add 'agent-assisted' label (may not exist — run create_issues.sh)"
fi

# Remove 'needs-review' if all DoR items passed (signals Ready)
if [[ "$failed_count" -eq 0 && "$skipped_count" -eq 0 ]]; then
  read -rp "All ${passed_count} DoR items passed. Remove 'needs-review' to signal Ready? [y/N]: " remove_review
  if [[ "${remove_review,,}" == "y" || "${remove_review,,}" == "yes" ]]; then
    gh issue edit "$issue_num" --remove-label "needs-review" 2>/dev/null && \
      echo "  Removed label: needs-review (issue is now Ready)" || \
      echo "  (needs-review label was not present or could not be removed)"
  fi
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "============================================================"
echo "  Refinement Summary: Issue #${issue_num}"
echo ""
echo "  DoR items passed:  ${passed_count}"
echo "  DoR items failed:  ${failed_count}"
echo "  Skipped:           ${skipped_count}"
echo ""
if [[ "$failed_count" -gt 0 ]]; then
  echo "  STATUS: NOT READY"
  echo "  Address the ${failed_count} failing item(s) before adding to sprint."
elif [[ "$skipped_count" -gt 0 ]]; then
  echo "  STATUS: CONDITIONALLY READY (${skipped_count} item(s) skipped)"
  echo "  Confirm skipped items are already met before sprint start."
else
  echo "  STATUS: READY"
  echo "  Issue can be added to the sprint."
fi
echo ""
echo "  View issue: gh issue view ${issue_num}"
echo "  Refine more: bash scripts/refine_issue.sh <N>"
echo "============================================================"
