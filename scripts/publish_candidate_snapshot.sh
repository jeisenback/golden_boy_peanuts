#!/usr/bin/env bash
# Publish data/candidates/*.json to the `data` branch (issue #218).
#
# Runs in the nightly workflow after write_candidate_snapshot.py. Never touches the
# checked-out branch: the snapshot is committed from a separate worktree on `data`,
# which is created as an orphan branch on the first run. Never pushes anywhere else.
#
# Usage: bash scripts/publish_candidate_snapshot.sh [snapshot_dir]   (default data/candidates)
set -euo pipefail

SRC_DIR="${1:-data/candidates}"
BRANCH="data"
REMOTE="${PUBLISH_REMOTE:-origin}"

if ! compgen -G "${SRC_DIR}/*.json" > /dev/null; then
    echo "No snapshot files in ${SRC_DIR}; nothing to publish." >&2
    exit 1
fi

STAGE="$(mktemp -d)"
WORKTREE="$(mktemp -d)"
trap 'git worktree remove --force "${WORKTREE}" 2>/dev/null || true; rm -rf "${STAGE}" "${WORKTREE}"' EXIT
cp "${SRC_DIR}"/*.json "${STAGE}/"

if git ls-remote --exit-code --heads "${REMOTE}" "${BRANCH}" > /dev/null 2>&1; then
    git fetch --quiet "${REMOTE}" "${BRANCH}"
    git worktree add --quiet -B "${BRANCH}" "${WORKTREE}" "${REMOTE}/${BRANCH}"
else
    git worktree add --quiet --detach "${WORKTREE}"
    git -C "${WORKTREE}" checkout --quiet --orphan "${BRANCH}"
    git -C "${WORKTREE}" rm -rf --quiet . || true
fi

mkdir -p "${WORKTREE}/data/candidates"
cp "${STAGE}"/*.json "${WORKTREE}/data/candidates/"
git -C "${WORKTREE}" add data/candidates

if git -C "${WORKTREE}" diff --cached --quiet; then
    echo "Snapshot unchanged; nothing to commit."
    exit 0
fi

git -C "${WORKTREE}" \
    -c user.name="github-actions[bot]" \
    -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
    commit --quiet -m "data: candidate snapshot $(basename "$(ls "${STAGE}"/*.json | tail -1)" .json)"
git -C "${WORKTREE}" push "${REMOTE}" "HEAD:refs/heads/${BRANCH}"
