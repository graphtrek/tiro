#!/usr/bin/env bash
# Runs `uv sync` in every sub-project (any directory with a pyproject.toml),
# each into its own isolated .venv. Unlike a plain shell loop with `set -e`,
# one project's failure doesn't stop the rest — every project is attempted
# and a pass/fail summary is printed at the end.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="$HOME/.local/bin:$PATH"

GREEN='\033[0;32m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

OK=()
FAILED=()

cd "$ROOT"
for pyproject in */pyproject.toml; do
    dir="$(dirname "$pyproject")"
    echo ""
    echo -e "${CYAN}== $dir ==${NC}"

    (cd "$ROOT/$dir" && uv sync)

    if [[ $? -eq 0 ]]; then
        OK+=("$dir")
    else
        FAILED+=("$dir")
    fi
done

echo ""
echo -e "${CYAN}Summary${NC}"
for d in "${OK[@]}"; do
    printf "  ${GREEN}%-24s${NC} synced\n" "$d"
done
for d in "${FAILED[@]}"; do
    printf "  ${RED}%-24s${NC} FAILED\n" "$d"
done

if [[ ${#FAILED[@]} -gt 0 ]]; then
    echo ""
    echo -e "${RED}${#FAILED[@]} project(s) failed to sync — see output above for the actual error.${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}All ${#OK[@]} project(s) synced.${NC}"
