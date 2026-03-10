#!/usr/bin/env bash
# new_branch.sh
#
# Interactive helper: creates and checks out a correctly named branch
# from develop, following the SDLC branch naming convention.
#
# Branch types: feature | fix | chore | agent
# Output branch: <type>/<issue-number>-<slug>
#
# Usage: bash scripts/new_branch.sh
# Requirements: git, must be run from repo root.

set -euo pipefail

echo ""
echo "=== New Branch Helper (SDLC v1.0) ==="
echo ""

# --- Branch type ---
echo "Branch type:"
echo "  1) feature   — new capability, agent, signal"
echo "  2) fix       — bug fix or defect correction"
echo "  3) chore     — tooling, deps, docs, config"
echo "  4) agent     — Claude Code / Cursor agent session"
echo ""
read -rp "Select type [1-4]: " type_choice

case "$type_choice" in
  1) BRANCH_TYPE="feature" ;;
  2) BRANCH_TYPE="fix" ;;
  3) BRANCH_TYPE="chore" ;;
  4) BRANCH_TYPE="agent" ;;
  *)
    echo "ERROR: Invalid selection. Choose 1, 2, 3, or 4."
    exit 1
    ;;
esac

# --- Issue number ---
echo ""
read -rp "GitHub Issue number (e.g. 42): " issue_number

if ! [[ "$issue_number" =~ ^[0-9]+$ ]]; then
  echo "ERROR: Issue number must be numeric."
  exit 1
fi

# --- Short slug ---
echo ""
echo "Short slug: lowercase words separated by hyphens."
echo "  Example: 'ingest-eia-feed'  or  'scaffold-event-detector'"
echo ""
read -rp "Slug: " raw_slug

# Sanitize: lowercase, replace spaces/underscores with hyphens, strip non-alnum-hyphen
slug=$(echo "$raw_slug" | tr '[:upper:]' '[:lower:]' | tr ' _' '-' | tr -cd '[:alnum:]-')

if [[ -z "$slug" ]]; then
  echo "ERROR: Slug cannot be empty."
  exit 1
fi

BRANCH_NAME="${BRANCH_TYPE}/${issue_number}-${slug}"

echo ""
echo "Branch to create: ${BRANCH_NAME}"
read -rp "Confirm? [y/N]: " confirm

if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
  echo "Aborted."
  exit 0
fi

# --- Ensure we are on a clean develop ---
current_branch=$(git symbolic-ref --short HEAD 2>/dev/null || echo "DETACHED")

if [[ "$current_branch" != "develop" ]]; then
  echo ""
  echo "WARNING: You are currently on '${current_branch}', not 'develop'."
  read -rp "Switch to develop first? [y/N]: " switch_confirm
  if [[ "$switch_confirm" == "y" || "$switch_confirm" == "Y" ]]; then
    git checkout develop
    git pull origin develop
  else
    echo "Aborted. Branch must be created from develop per SDLC Section 4.1."
    exit 1
  fi
else
  echo "Pulling latest develop..."
  git pull origin develop
fi

# --- Create and checkout branch ---
git checkout -b "$BRANCH_NAME"

echo ""
echo "=== Done ==="
echo "Branch created and checked out: ${BRANCH_NAME}"
echo ""
echo "Next steps (ADLC Section 2):"
echo "  1. Open or reference GitHub Issue #${issue_number}"
echo "  2. Fill in the Claude Code prompt template if agent-assisted"
echo "     (see docs/prompts/ for templates)"
echo "  3. Run your agent session or implement the change"
echo "  4. When done: bash scripts/post_session.sh"
echo ""
