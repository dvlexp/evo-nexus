#!/usr/bin/env bash
# Install EvoNexus git hooks into .git/hooks/.
#
# Usage:
#   bash scripts/git-hooks/install.sh
#
# This copies the pre-commit hook from scripts/git-hooks/ to .git/hooks/
# and marks it executable. Re-run after pulling updates to scripts/git-hooks/.

set -euo pipefail

REPO_ROOT=$(git rev-parse --show-toplevel)
HOOKS_SRC="$REPO_ROOT/scripts/git-hooks"
HOOKS_DST="$REPO_ROOT/.git/hooks"

if [ ! -d "$HOOKS_DST" ]; then
    echo "ERROR: $HOOKS_DST does not exist. Are you inside a git repo?"
    exit 1
fi

for hook in pre-commit; do
    src="$HOOKS_SRC/$hook"
    dst="$HOOKS_DST/$hook"
    if [ ! -f "$src" ]; then
        echo "skip: $src not found"
        continue
    fi
    cp "$src" "$dst"
    chmod +x "$dst"
    echo "installed: $dst"
done

if ! command -v gitleaks >/dev/null 2>&1; then
    echo
    echo "WARNING: gitleaks is not installed. The pre-commit hook will skip"
    echo "the secret scan until gitleaks is available on PATH. Install with:"
    echo
    echo "  curl -fsSL https://github.com/gitleaks/gitleaks/releases/download/v8.21.2/gitleaks_8.21.2_linux_x64.tar.gz -o /tmp/gitleaks.tgz"
    echo "  tar -xz -C /tmp -f /tmp/gitleaks.tgz gitleaks"
    echo "  sudo mv /tmp/gitleaks /usr/local/bin/ && sudo chmod +x /usr/local/bin/gitleaks"
fi

echo
echo "Done. Test with: gitleaks protect --staged --config=.gitleaks.toml --no-banner --redact"
