#!/usr/bin/env bash
# Starts all Tiro services defined in .vscode/launch.json.
# Logs go to logs/<service>.log, and are also fanned into a combined,
# tagged and timestamped logs/all.log. Press Ctrl+C to stop everything.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGS="$ROOT/logs"
mkdir -p "$LOGS"
rm -f "$LOGS"/*.log

ALL_LOG="$LOGS/all.log"
: >"$ALL_LOG"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

# Distinct per-service colors for the [name] tag in the combined logs/all.log,
# assigned round-robin in start order.
TAG_COLORS=('\033[0;32m' '\033[0;33m' '\033[0;34m' '\033[0;35m' '\033[0;36m' '\033[0;91m' '\033[0;94m' '\033[0;95m')
COLOR_IDX=0

PIDS=()
NAMES=()
TAIL_PIDS=()

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

    # Fan this service's log into the consolidated logs/all.log, tagged,
    # timestamped, and colorized per-service (the tag only, not the message).
    local tag_color="${TAG_COLORS[$((COLOR_IDX % ${#TAG_COLORS[@]}))]}"
    COLOR_IDX=$((COLOR_IDX + 1))
    ( tail -n +1 -F "$log" 2>/dev/null | while IFS= read -r line; do
          printf "${tag_color}[%s] [%s]${NC} %s\n" "$(date '+%H:%M:%S')" "$name" "$line"
      done ) >>"$ALL_LOG" &
    TAIL_PIDS+=("$!")
}

# Recursively gather a PID and all its descendants into ALL_PIDS.
# Needed because each `start`ed job is really "subshell -> python -> (maybe)
# uvicorn --reload worker" and only the subshell PID is captured by $! —
# signaling just that PID leaves the real python process orphaned.
collect_tree() {
    local pid=$1
    ALL_PIDS+=("$pid")
    local child
    for child in $(pgrep -P "$pid" 2>/dev/null); do
        collect_tree "$child"
    done
}

_CLEANED=0
cleanup() {
    (( _CLEANED )) && return
    _CLEANED=1
    trap - EXIT INT TERM
    echo ""
    echo -e "${YELLOW}Stopping services...${NC}"

    ALL_PIDS=()
    for i in "${!PIDS[@]}"; do
        collect_tree "${PIDS[$i]}"
    done
    for pid in "${TAIL_PIDS[@]}"; do
        collect_tree "$pid"
    done

    for pid in "${ALL_PIDS[@]}"; do
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
        kill -0 "$pid" 2>/dev/null && kill -KILL "$pid" 2>/dev/null
    done

    for i in "${!PIDS[@]}"; do
        printf "  stopped %-34s (pid %s)\n" "${NAMES[$i]}" "${PIDS[$i]}"
    done

    wait 2>/dev/null
    echo -e "${GREEN}All services stopped.${NC}"
    exit 0
}
trap cleanup EXIT INT TERM

echo ""
echo -e "${CYAN}Starting Tiro services${NC}"
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
printf "  ${CYAN}%-34s${NC}          logs/all.log (combined)\n" "all services"
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
