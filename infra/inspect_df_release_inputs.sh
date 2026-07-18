#!/usr/bin/env bash
set -euo pipefail

pct exec 123 -- bash -lc '
set -euo pipefail
df_stage=/srv/df-bonsai/staging/df-steam
dfhack_stage=/srv/df-bonsai/staging/dfhack/53.15-r2/payload

echo "=== Dwarf Fortress version ==="
sed -n "1,60p" "$df_stage/VERSIONS.txt"
echo "=== Manifest ==="
grep -E "\"(appid|name|buildid|StateFlags)\"" "$df_stage/steamapps/appmanifest_975370.acf"
echo "=== Headless defaults ==="
grep -R -n -E "^\[(PRINT_MODE|SOUND):" "$df_stage/data/init" 2>/dev/null || true
echo "=== DFHack payload root ==="
find "$dfhack_stage" -maxdepth 2 -mindepth 1 -printf "%y %P\n" | sort | head -120
echo "=== DFHack version markers ==="
find "$dfhack_stage" -maxdepth 3 -type f \( -iname "*version*" -o -iname "readme*" \) -print | head -30
echo "=== Package candidates ==="
apt-cache policy libsdl2-2.0-0 libsdl2-image-2.0-0 | sed -n "1,80p"
'
