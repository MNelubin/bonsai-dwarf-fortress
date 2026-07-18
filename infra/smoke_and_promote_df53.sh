#!/usr/bin/env bash
set -euo pipefail

pct exec 123 -- bash -s <<'GUEST'
set -euo pipefail

release_id='df-53.15-steam-23622201_dfhack-53.15-r2'
root='/srv/df-bonsai'
release="$root/releases/$release_id"
instance="$root/state/instances/.smoke-$release_id-$$"
log="$root/logs/smoke-$release_id-$(date +%Y%m%dT%H%M%S).log"
port=5500
runner_pid=''
success=0

exec > >(tee -a "$log") 2>&1
echo "[$(date --iso-8601=seconds)] smoke test starting"

cleanup() {
    rc=$?
    if [[ -n "$runner_pid" ]] && kill -0 "$runner_pid" 2>/dev/null; then
        kill -TERM -- "-$runner_pid" 2>/dev/null || true
        sleep 2
        kill -KILL -- "-$runner_pid" 2>/dev/null || true
    fi
    if [[ $success -eq 1 ]]; then
        case "$instance" in
            "$root/state/instances/.smoke-"*) rm -rf -- "$instance" ;;
            *) echo "refusing to remove unexpected path: $instance" >&2 ;;
        esac
    else
        echo "[$(date --iso-8601=seconds)] smoke failed rc=$rc; instance retained at $instance"
    fi
}
trap cleanup EXIT

test -x "$release/dwarfort"
test -x "$release/dfhack"
grep -qx '\[SOUND:NO\]' "$release/data/init/init.txt"
grep -qx '\[PRINT_MODE:TEXT\]' "$release/data/init/init.txt"
chmod o+x "$root" "$root/state"
install -d -o dfbot -g dfbot -m 0750 "$instance"

echo "[$(date --iso-8601=seconds)] copying isolated smoke instance"
rsync -a "$release/" "$instance/"
chown -R dfbot:dfbot "$instance"
chmod -R u+rwX "$instance"

echo "[$(date --iso-8601=seconds)] launching DFHack headless on loopback RPC port $port"
cd "$instance"
setsid runuser -u dfbot -- env \
    HOME="$root/state/home" \
    DFHACK_HEADLESS=1 \
    DFHACK_DISABLE_CONSOLE=1 \
    DFHACK_PORT="$port" \
    SDL_AUDIODRIVER=dummy \
    ./dfhack >"$log.game" 2>&1 &
runner_pid=$!

for attempt in $(seq 1 30); do
    if ! kill -0 "$runner_pid" 2>/dev/null; then
        echo "game process exited before RPC became ready" >&2
        tail -100 "$log.game" >&2 || true
        exit 1
    fi
    if grep -Fq 'DFHack is running.' "$instance/stderr.log" 2>/dev/null \
        && grep -Fq 'DFHack build 53.15-r2' "$instance/stderr.log" 2>/dev/null \
        && ss -H -lnt | awk -v endpoint="127.0.0.1:$port" '$4 == endpoint {found=1} END {exit !found}'; then
        echo "[$(date --iso-8601=seconds)] DFHack ready; loopback RPC is listening"
        grep -E 'DFHack is running|DFHack build 53[.]15-r2' "$instance/stderr.log" | tail -2
        success=1
        break
    fi
    if (( attempt % 5 == 0 )); then
        echo "[$(date --iso-8601=seconds)] waiting for RPC ($attempt/30)"
    fi
    sleep 2
done

if [[ $success -ne 1 ]]; then
    echo "DFHack did not become ready" >&2
    tail -100 "$log.game" >&2 || true
    exit 1
fi

kill -TERM -- "-$runner_pid" 2>/dev/null || true
for _ in $(seq 1 10); do
    kill -0 "$runner_pid" 2>/dev/null || break
    sleep 1
done
kill -KILL -- "-$runner_pid" 2>/dev/null || true
runner_pid=''

new_link="$root/.current.new.$$"
ln -s "$release" "$new_link"
mv -Tf "$new_link" "$root/current"
echo "[$(date --iso-8601=seconds)] promoted current -> $release"
GUEST
