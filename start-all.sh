#!/usr/bin/env bash
# Starts all Moneypenny services defined in .vscode/launch.json.
# Logs go to logs/<service>.log. Press Ctrl+C to stop everything.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGS="$ROOT/logs"
mkdir -p "$LOGS"
rm -f "$LOGS"/*.log

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

PIDS=()
NAMES=()

start() {
    local name=$1 dir=$2 python=$3 script=$4
    local log="$LOGS/${name}.log"

    if [[ ! -d "$ROOT/$dir" || ! -f "$ROOT/$python" || ! -f "$ROOT/$script" ]]; then
        printf "  ${RED}%-34s${NC} skipped (not found)\n" "$name"
        return
    fi

    (cd "$ROOT/$dir" && "$ROOT/$python" "$ROOT/$script") >"$log" 2>&1 &
    local pid=$!
    PIDS+=("$pid")
    NAMES+=("$name")
    printf "  ${GREEN}%-34s${NC} pid %-6s  logs/%s.log\n" "$name" "$pid" "$name"
}

_CLEANED=0
cleanup() {
    (( _CLEANED )) && return
    _CLEANED=1
    trap - EXIT INT TERM
    echo ""
    echo -e "${YELLOW}Stopping services...${NC}"
    for i in "${!PIDS[@]}"; do
        local pid="${PIDS[$i]}"
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
            printf "  stopped %-34s (pid %s)\n" "${NAMES[$i]}" "$pid"
        fi
    done
    wait 2>/dev/null
    echo -e "${GREEN}All services stopped.${NC}"
    exit 0
}
trap cleanup EXIT INT TERM

echo ""
echo -e "${CYAN}Starting Moneypenny services${NC}"
echo ""

# Leaf services (no upstream dependencies)
start "auth (8007)"                  "auth"                  "auth/.venv/bin/python"                  "auth/run_api.py"
start "attachment-downloader (8000)" "attachment-downloader" "attachment-downloader/.venv/bin/python" "attachment-downloader/run_api.py"
start "nav-invoice (8002)"           "nav-invoice"           "nav-invoice/.venv/bin/python"           "nav-invoice/run_api.py"
start "bank (8005)"                  "bank"                  "bank/.venv/bin/python"                  "bank/run_api.py"
start "uploader (8006)"              "uploader"              "uploader/.venv/bin/python"              "uploader/run_api.py"

# Brief pause so leaf services are listening before dependents start
sleep 2

# Dependent services
start "invoice-file-filter (8001)"   "invoice-file-filter"   "invoice-file-filter/.venv/bin/python"   "invoice-file-filter/run_api.py"
start "invoice-core (8004)"          "invoice-core"          "invoice-core/.venv/bin/python"          "invoice-core/run_api.py"
start "vision (8009)"                "vision"                "vision/.venv/bin/python"                "vision/run_api.py"

echo ""
echo -e "${GREEN}All services started. Press Ctrl+C to stop.${NC}"
echo ""

# Monitor: report if any service exits unexpectedly; stop when all are gone
while true; do
    sleep 5
    alive=0
    for i in "${!PIDS[@]}"; do
        if [[ -n "${PIDS[$i]}" ]]; then
            if ! kill -0 "${PIDS[$i]}" 2>/dev/null; then
                echo -e "${RED}[$(date '+%H:%M:%S')] '${NAMES[$i]}' exited unexpectedly — check logs/${NAMES[$i]}.log${NC}"
                unset "PIDS[$i]"
            else
                (( alive++ )) || true
            fi
        fi
    done
    if (( alive == 0 )); then
        echo -e "${RED}All services have stopped.${NC}"
        break
    fi
done
