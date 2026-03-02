#!/usr/bin/env bash
# =============================================================================
# Install Git Hooks for AIReceptionist
#
# Usage: bash scripts/install-hooks.sh
#
# This script copies the pre-commit hook from scripts/pre-commit into the
# repository's .git/hooks/ directory and makes it executable.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HOOK_SOURCE="$SCRIPT_DIR/pre-commit"
HOOK_TARGET="$REPO_ROOT/.git/hooks/pre-commit"

# Colors
if [ -t 1 ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    CYAN='\033[0;36m'
    BOLD='\033[1m'
    NC='\033[0m'
else
    RED=''
    GREEN=''
    CYAN=''
    BOLD=''
    NC=''
fi

echo ""
echo -e "${CYAN}${BOLD}[install-hooks]${NC} Installing git hooks for AIReceptionist..."
echo ""

# Check we're in a git repository
if [ ! -d "$REPO_ROOT/.git" ]; then
    echo -e "${RED}Error: No .git directory found at $REPO_ROOT${NC}"
    echo -e "${RED}Make sure you run this from within the AIReceptionist repository.${NC}"
    exit 1
fi

# Check the hook source exists
if [ ! -f "$HOOK_SOURCE" ]; then
    echo -e "${RED}Error: Hook source not found at $HOOK_SOURCE${NC}"
    exit 1
fi

# Create hooks directory if it doesn't exist
mkdir -p "$REPO_ROOT/.git/hooks"

# Copy the pre-commit hook
cp "$HOOK_SOURCE" "$HOOK_TARGET"
chmod +x "$HOOK_TARGET"

echo -e "  ${GREEN}Installed:${NC} pre-commit -> .git/hooks/pre-commit"
echo ""
echo -e "${GREEN}${BOLD}[install-hooks]${NC}${GREEN} Done. The pre-commit hook will now run on every commit.${NC}"
echo ""
echo -e "The hook will:"
echo -e "  1. Warn if receptionist/ code changed without documentation updates"
echo -e "  2. Run pytest and block the commit if tests fail"
echo ""
