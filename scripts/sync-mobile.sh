#!/usr/bin/env bash
# Sync a commit's mobile/ changes to the `mobileapp` branch — automatically.
#
# Safe by design:
#   - never switches your current branch (uses a throwaway git worktree)
#   - only touches mobile/ files (backend/frontend/ML code never lands on mobileapp)
#   - idempotent + non-fatal: if there's nothing to sync or it can't apply
#     cleanly, it exits 0 without breaking your commit
#
# Usage:  bash scripts/sync-mobile.sh [commit]   (defaults to HEAD)
set -uo pipefail

# CRITICAL: git hooks export GIT_DIR/GIT_WORK_TREE/etc into child processes,
# which breaks `git worktree add` (it thinks it's already inside a worktree).
# Clear them so git commands here operate on the repo normally.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_PREFIX GIT_COMMON_DIR \
      GIT_INDEX_VERSION GIT_REFLOG_ACTION 2>/dev/null || true

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMMIT="${1:-HEAD}"
SHA="$(git rev-parse --short "$COMMIT" 2>/dev/null)" || exit 0
# Resolve the FULL sha now (in the main repo). Inside the worktree, "HEAD"/the
# ref would point at mobileapp, not the source commit — must use the explicit sha.
FULL_SHA="$(git rev-parse "$COMMIT" 2>/dev/null)" || exit 0
SRC_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"

# Skip if this commit doesn't touch mobile/
if ! git show --stat --name-only --format="" "$COMMIT" | grep -q '^mobile/'; then
  exit 0
fi
# Don't sync commits made ON the mobileapp branch itself
[ "$SRC_BRANCH" = "mobileapp" ] && exit 0

git fetch -q origin mobileapp 2>/dev/null || true
git worktree prune >/dev/null 2>&1 || true   # clear any stale worktree state first

# git worktree add requires a NON-existent path, so use a subdir of mktemp's dir
WT="$(mktemp -d)/wt"
cleanup() { git worktree remove --force "$WT" >/dev/null 2>&1 || true; git worktree prune >/dev/null 2>&1 || true; }
trap cleanup EXIT

# DETACHED worktree at the remote mobileapp tip (avoids clashing with the
# local 'mobileapp' branch / current checkout). We push HEAD:mobileapp.
if ! git worktree add -q --detach "$WT" origin/mobileapp 2>/dev/null; then
  echo "[sync-mobile] could not create worktree — skipping"; exit 0
fi

# Mirror the source commit's mobile/ tree exactly onto mobileapp (handles
# additions, modifications AND deletions — git apply missed file removals).
# Remove mobile/ from BOTH index and working tree, then restore it from the
# source commit — guarantees deletions propagate (rm --cached left files behind,
# so add -A re-added them). Safety: only proceed if the restored tree is non-empty.
git -C "$WT" rm -r -q --ignore-unmatch mobile/ >/dev/null 2>&1 || true
git -C "$WT" checkout "$FULL_SHA" -- mobile/ 2>/dev/null || true
if [ -z "$(git -C "$WT" ls-files mobile/)" ]; then
  echo "[sync-mobile] restored mobile/ is empty — aborting to avoid wiping mobileapp"; exit 0
fi
git -C "$WT" add -A mobile/

if git -C "$WT" diff --cached --quiet; then
  echo "[sync-mobile] mobile/ already matches mobileapp — nothing to do"
else
  MSG="$(git log -1 --format=%s "$COMMIT")"
  # core.hooksPath=/dev/null → this internal commit must NOT re-fire post-commit
  git -C "$WT" -c core.hooksPath=/dev/null \
      -c user.name="$(git config user.name)" \
      -c user.email="$(git config user.email)" \
      commit -q -m "${MSG} (auto-synced from ${SRC_BRANCH}@${SHA})"
  if git -C "$WT" push -q origin HEAD:mobileapp; then
    echo "[sync-mobile] ✓ synced mobile/ changes (${SHA}) → mobileapp"
  else
    echo "[sync-mobile] push to mobileapp failed (remote moved — run sync again)"
  fi
fi
