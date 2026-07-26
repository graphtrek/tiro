#!/usr/bin/env bash
# Kills any lingering python processes belonging to this workspace's services
# (e.g. after a closed terminal, a crashed start-all.sh, or a stray manual run).
# Scoped to processes whose executable is a python interpreter AND whose
# command line runs from this repo's path — never touches unrelated python
# processes elsewhere on the machine (Jupyter, other projects, etc).

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SELF_PID=$$

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Recursively gather a PID and all its descendants (covers any uvicorn
# --reload supervisor/worker child that isn't its own top-level match).
collect_tree() {
    local pid=$1
    ALL_PIDS+=("$pid")
    local child
    for child in $(pgrep -P "$pid" 2>/dev/null); do
        collect_tree "$child"
    done
}

TOP_PIDS=()
while IFS= read -r pid; do
    [[ -n "$pid" ]] && TOP_PIDS+=("$pid")
done < <(
    ps -eo pid=,command= | awk -v root="$ROOT" -v self="$SELF_PID" '
        $1 == self { next }
        tolower($2) ~ /python/ && index($0, root) > 0 { print $1 }
    '
)

if (( ${#TOP_PIDS[@]} == 0 )); then
    echo -e "${GREEN}No lingering python processes found for this workspace.${NC}"
    exit 0
fi

ALL_PIDS=()
for pid in "${TOP_PIDS[@]}"; do
    collect_tree "$pid"
done

echo -e "${YELLOW}Stopping ${#ALL_PIDS[@]} python process(es)...${NC}"
for pid in "${ALL_PIDS[@]}"; do
    cmd=$(ps -p "$pid" -o command= 2>/dev/null)
    printf "  pid %-8s %s\n" "$pid" "$cmd"
    kill -TERM "$pid" 2>/dev/null
done

for _ in 1 2 3 4 5; do
    remaining=0
    for pid in "${ALL_PIDS[@]}"; do
        kill -0 "$pid" 2>/dev/null && (( remaining++ ))
    done
    (( remaining == 0 )) && break
    sleep 1
done

for pid in "${ALL_PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
        kill -KILL "$pid" 2>/dev/null
        echo -e "  ${RED}force-killed pid $pid${NC}"
    fi
done

echo -e "${GREEN}Done.${NC}"
