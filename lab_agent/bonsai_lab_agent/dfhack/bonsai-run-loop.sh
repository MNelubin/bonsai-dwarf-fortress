#!/usr/bin/env bash
# External episode driver. DFHack timer callbacks can rescan digging, but live evidence
# shows that creating workshop jobs from inside an unpaused callback is refused without
# an error. Alternate simulation chunks with a paused pump RPC, exactly like a player
# pausing to issue orders.
set -u
TOTAL=${1:-40000}
PERIOD=${2:-1000}
CHUNK=${3:-5000}
ACTIONS=${4:-/tmp/bonsai-actions-${DFHACK_PORT:-x}.tsv}
PORT=${DFHACK_PORT:?DFHACK_PORT must be set}
WATCH=/tmp/orderwatch.$PORT.log

run() { DFHACK_PORT=$PORT timeout 15 ./dfhack-run "$@" >/dev/null 2>&1 || true; }
done_frames=0
while (( done_frames < TOTAL )); do
    step=$CHUNK
    (( done_frames + step > TOTAL )) && step=$((TOTAL - done_frames))
    before=$(grep -c '^END ' "$WATCH" 2>/dev/null || true)
    run bonsai-run "$step" "$PERIOD"
    for _ in $(seq 1 180); do
        after=$(grep -c '^END ' "$WATCH" 2>/dev/null || true)
        (( after > before )) && break
        sleep 1
    done
    (( after > before )) || { echo "RUN_LOOP_TIMEOUT frames=$done_frames"; exit 1; }
    run bonsai-apply-actions "$ACTIONS" pump
    done_frames=$((done_frames + step))
done
echo "RUN_LOOP_DONE frames=$done_frames actions=$ACTIONS"
