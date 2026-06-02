#!/usr/bin/env bash
# Install local git hooks (not tracked in .git). Run once after cloning:
#   bash scripts/install-hooks.sh
#
# Installs a post-commit hook that auto-syncs mobile/ changes to the
# `mobileapp` branch (see scripts/sync-mobile.sh). Non-blocking and safe.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$ROOT/.git/hooks/post-commit"

cat > "$HOOK" <<'EOF'
#!/usr/bin/env bash
# Auto-sync mobile/ changes to the mobileapp branch (non-blocking, never fails the commit)
ROOT="$(git rev-parse --show-toplevel)"
mkdir -p "$ROOT/.logs"
nohup bash "$ROOT/scripts/sync-mobile.sh" HEAD >> "$ROOT/.logs/sync-mobile.log" 2>&1 &
EOF

chmod +x "$HOOK"
echo "✓ post-commit hook installed → $HOOK"
echo "  mobile/ changes will now auto-sync to the 'mobileapp' branch on every commit."
