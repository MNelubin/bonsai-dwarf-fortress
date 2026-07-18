#!/usr/bin/env bash
set -euo pipefail

pct exec 123 -- bash -s <<'GUEST'
set -euo pipefail

release_id='df-53.15-steam-23622201_dfhack-53.15-r2'
root='/srv/df-bonsai'
df_stage="$root/staging/df-steam"
dfhack_stage="$root/staging/dfhack/53.15-r2/payload"
release="$root/releases/$release_id"
building="$root/releases/.building-$release_id-$$"
log="$root/logs/build-$release_id.log"

exec > >(tee -a "$log") 2>&1
echo "[$(date --iso-8601=seconds)] starting release build"

test -x "$df_stage/dwarfort"
test -x "$dfhack_stage/dfhack"
test ! -e "$release"

if ! id -u dfbot >/dev/null 2>&1; then
    useradd --system --home-dir "$root/state/home" --shell /usr/sbin/nologin dfbot
fi
install -d -o dfbot -g dfbot -m 0750 "$root/state/home" "$root/state/instances"
# Allow the runtime account to traverse to its own state and read-only release.
# Directory listings remain unavailable, and /srv/steam stays isolated.
chmod o+x "$root" "$root/state"

cleanup() {
    rc=$?
    if [[ $rc -eq 0 ]]; then
        rm -rf -- "$building"
    else
        echo "[$(date --iso-8601=seconds)] build failed with rc=$rc; partial tree retained at $building"
    fi
}
trap cleanup EXIT

install -d -m 0755 "$building"
rsync -a --delete "$df_stage/" "$building/"
rsync -a "$dfhack_stage/" "$building/"

cp "$building/data/init/init_default.txt" "$building/data/init/init.txt"
sed -i \
    -e 's/\r$//' \
    -e 's/^\[SOUND:YES\]$/[SOUND:NO]/' \
    -e 's/^\[PRINT_MODE:AUTO\]$/[PRINT_MODE:TEXT]/' \
    "$building/data/init/init.txt"

missing="$({ ldd "$building/dwarfort"; ldd "$building/hack/libdfhack.so"; } | awk '/not found/{print}')"
if [[ -n "$missing" ]]; then
    printf '%s\n' "$missing" >&2
    exit 1
fi

dfhack_sha256="$(sha256sum "$root/staging/dfhack/53.15-r2/dfhack-53.15-r2-Linux-64bit.tar.bz2" | awk '{print $1}')"
jq -n \
    --arg release_id "$release_id" \
    --arg created_at "$(date --iso-8601=seconds)" \
    --arg df_version '53.15' \
    --arg steam_appid '975370' \
    --arg steam_buildid '23622201' \
    --arg dfhack_version '53.15-r2' \
    --arg dfhack_sha256 "$dfhack_sha256" \
    '{release_id:$release_id,created_at:$created_at,dwarf_fortress:{version:$df_version,steam_appid:$steam_appid,buildid:$steam_buildid},dfhack:{version:$dfhack_version,archive_sha256:$dfhack_sha256},headless:{print_mode:"TEXT",sound:false}}' \
    > "$building/DF-BONSAI-RELEASE.json"

chmod -R a-w "$building"
mv "$building" "$release"
trap - EXIT

echo "Built immutable release: $release"
cat "$release/DF-BONSAI-RELEASE.json"
GUEST
