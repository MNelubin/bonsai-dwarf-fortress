# Mechanics: Buildings

This note documents the DFHack building commands observed in the live runtime.

## Command Overview

- **burial**: Creates tomb zones for unzoned coffins. Tags: buildings, fort, productivity
- **burrow**: Quickly adjusts burrow tiles and units. Tags: auto, design, fort, productivity, units
- **buildingplan**: Plans building placement before materials are available. Tags: buildings, design, fort, productivity
- **build-now**: Instantly completes building construction jobs. Tags: armok, buildings, fort

## VERIFIED Claims

Each command exists in the DFHack runtime and has associated tags. Verified via `dfhack-run ls fort`:
```
BONSAI_PROBE_RESULT {
  "command": ["/srv/df-bonsai/releases/df-53.15-steam-23622201_dfhack-53.15-r2/dfhack-run", "ls", "fort"],
  "output": "burial               Create tomb zones for unzoned coffins.\n  ..."
}
```

## Coding Task

Create a Lua script to list all buildings with construction status in JSON format. The script should:
1. Iterate over all tiles
2. Extract building identifiers and construction progress
3. Output to a temporary file in /tmp

Test: Run `/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 120 -- dfhack-run lua building-probe.lua` and verify the JSON file contains at least 100 building entries.

## TODO
- [x] Add command examples
- [x] Write Lua script
- [x] Create test harness
