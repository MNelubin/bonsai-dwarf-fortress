---
# Pause, Advance, and Time Mechanics

## Overview
This note documents the structural availability of time-control mechanisms (pause/advance) within the Dwarf Fortress 53.15 / DFHack 53.15-r2 environment. It identifies where these controls are likely implemented based on file system inspection and highlights gaps in current verification.

## Installation Context [VERIFIED]
The target environment is located at `/srv/df-bonsai/current`, which resolves to `df-53.15-steam-23622201_dfhack-53.15-r2` [VERIFIED via `bridge-primitives.md` and `ls /srv/df-bonsai/current/`].

## Structural Evidence for Time Control APIs

### 1. DFHack Lua Core Libraries [VERIFIED]
The directory `/srv/df-bonsai/current/hack/lua/` contains the core DFHack Lua implementation.
- **Path**: `/srv/df-bonsai/current/hack/lua/dfhack/`
- **Contents**: `buildings.lua`, `workshops.lua` [VERIFIED via `ls /srv/df-bonsai/current/hack/lua/dfhack/`].
- **Implication**: Standard DFHack Lua modules are present. Time control APIs (e.g., `dfhack.pause()`, `dfhack.advance()`) are typically exposed in the main `dfhack.lua` or via C-module bindings loaded by `libdfhack.so`. The absence of explicit `time.lua` in the top-level lua directory suggests time controls may be embedded in the core `dfhack` namespace or handled via lower-level hooks.

### 2. Plugin Availability [VERIFIED]
The directory `/srv/df-bonsai/current/hack/plugins/` contains compiled plugins (`.plug.so`).
- **Relevant Plugins**:
  - `probe.plug.so`: Likely provides diagnostic capabilities, potentially including tick/state inspection.
  - `debug.plug.so`: May expose internal game state variables such as ticks or calendar year.
  - `fastdwarf.plug.so`: Historically associated with speed adjustments; may interact with pause/advance logic.
- **Verification**: Presence confirmed via `ls /srv/df-bonsai/current/hack/plugins/` [VERIFIED].

### 3. Configuration and Init Scripts [VERIFIED]
The directory `/srv/df-bonsai/current/dfhack-config/init/` contains initialization scripts.
- **Files**: `default.dfhack.init`, `onLoad.init`, etc. [VERIFIED via `ls /srv/df-bonsai/current/dfhack-config/init/`].
- **Implication**: These scripts may set initial pause states or register hooks for time advancement. No explicit "pause" or "advance" keywords were found in a grep of `/srv/df-bonsai/current/dfhack-config/scripts/` [VERIFIED via `grep -rl ...` returning no output].

## Gaps and Uncertainties [OPEN]
1. **API Signature**: The exact Lua function signatures for pausing or advancing time (e.g., `dfhack.pause(true)`, `dfhack.advance(100)`) are not explicitly verified in the trace. While standard DFHack documentation suggests these exist, their availability in this specific build (`53.15-r2`) is assumed but not proven by direct code inspection of `libdfhack.so` or `dfhack.lua` content.
2. **Tick State Access**: The method to read the current game tick or calendar year via Lua is not explicitly demonstrated. It is inferred that `df.global.world.time` or similar structures are accessible, but this remains [OPEN] without a successful probe result.
3. **Live Probe Failure**: Attempts to run executable probes against the live DF/DFHack instance were not completed due to budget exhaustion (`harness_budget_exhausted`). Therefore, no runtime state transitions (pause -> advance) were observed.

## Implications for Reset/Observe/Act/Advance

- **Reset**: Likely involves reloading the map or invoking a specific DFHack command. The presence of `onMapLoad.init` suggests hooks are available for reset events [INFERRED].
- **Observe**: Reading game state (ticks, calendar) requires accessing global variables via Lua. This is feasible given the presence of `libdfhack.so` and standard Lua bindings [INFERRED].
- **Act/Advance**: Controlling time flow is critical for automation. The lack of explicit script evidence in `dfhack-config/scripts/` suggests that time control may be handled via direct API calls rather than pre-written scripts [INFERRED].

## Coding Recommendations

1. **Verify Lua API Availability**:
   - Execute a simple Lua probe to check for `dfhack.pause` and `dfhack.advance` functions.
   - Example: `print(type(dfhack.pause))`
2. **Inspect Global Time State**:
   - Probe `df.global.world.time` or equivalent structures to read current ticks/calendar year.
3. **Leverage Plugins**:
   - If standard APIs are insufficient, investigate `probe.plug.so` or `debug.plug.so` for low-level state access.
4. **Handle Uncertainty**:
   - Treat time-control mechanisms as [OPEN] until verified by a successful live probe. Do not assume specific function signatures without confirmation.

## References
- `ls /srv/df-bonsai/current/hack/lua/` [VERIFIED]
- `ls /srv/df-bonsai/current/hack/plugins/` [VERIFIED]
- `grep -rl "pause\|advance\|clockyear\|ticks" /srv/df-bonsai/current/dfhack-config/scripts/` [VERIFIED: No matches]
- `file /srv/df-bonsai/current/dfhack` [VERIFIED: POSIX shell script]
