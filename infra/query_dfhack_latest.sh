#!/usr/bin/env bash
set -euo pipefail

pct exec 123 -- bash -lc \
    "curl -fsSL https://api.github.com/repos/DFHack/dfhack/releases/latest | jq -r '.tag_name, (.assets[]?.name)'"
