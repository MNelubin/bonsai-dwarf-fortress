#!/usr/bin/env bash
set -euo pipefail

pct exec 123 -- bash -s <<'GUEST'
set -euo pipefail

release_id='df-53.15-steam-23622201_dfhack-53.15-r2'
root='/srv/df-bonsai'
release="$root/releases/$release_id"
instance="$(find "$root/state/instances" -maxdepth 1 -type d -name ".smoke-$release_id-*" -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)"
port=5500
log="$root/logs/revalidate-$release_id-$(date +%Y%m%dT%H%M%S).log"
runner_pid=''
success=0

exec > >(tee -a "$log") 2>&1
echo "[$(date --iso-8601=seconds)] revalidation starting: $instance"

cleanup() {
    rc=$?
    if [[ -n "$runner_pid" ]] && kill -0 "$runner_pid" 2>/dev/null; then
        kill -TERM -- "-$runner_pid" 2>/dev/null || true
        sleep 2
        kill -KILL -- "-$runner_pid" 2>/dev/null || true
    fi
    if [[ $success -eq 1 ]]; then
        find "$root/state/instances" -maxdepth 1 -type d -name ".smoke-$release_id-*" -print0 \
            | while IFS= read -r -d '' stale; do
                case "$stale" in
                    "$root/state/instances/.smoke-$release_id-"*) rm -rf -- "$stale" ;;
                    *) echo "refusing unexpected cleanup path: $stale" >&2 ;;
                esac
            done
    else
        echo "[$(date --iso-8601=seconds)] revalidation failed rc=$rc"
    fi
}
trap cleanup EXIT

test -n "$instance"
test -x "$instance/dfhack"
rm -f -- "$instance/stderr.log" "$instance/stdout.log"
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
    kill -0 "$runner_pid" 2>/dev/null || { echo 'game exited early' >&2; exit 1; }
    if grep -Fq 'DFHack is running.' "$instance/stderr.log" 2>/dev/null \
        && grep -Fq 'DFHack build 53.15-r2' "$instance/stderr.log" 2>/dev/null \
        && ss -H -lnt | awk -v endpoint="127.0.0.1:$port" '$4 == endpoint {found=1} END {exit !found}'; then
        success=1
        break
    fi
    if (( attempt % 5 == 0 )); then
        echo "[$(date --iso-8601=seconds)] waiting for DFHack ($attempt/30)"
    fi
    sleep 2
done

test "$success" -eq 1
echo "[$(date --iso-8601=seconds)] validated headless process and loopback RPC"
grep -E 'DFHack is running|DFHack build 53[.]15-r2' "$instance/stderr.log" | tail -2
cp "$instance/stderr.log" "$log.dfhack-stderr"

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
