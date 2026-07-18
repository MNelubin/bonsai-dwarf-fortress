---
# DF-Bonsai Runtime Structure and File Layout

## Overview
This note details the physical file layout of the Dwarf Fortress runtime environment within the DF-Bonsai agent infrastructure. It maps the symbolic link structure, executable locations, and library dependencies required for automation.

## Target Versions
- **Dwarf Fortress**: 53.15 [VERIFIED]
- **DFHack**: 53.15-r2 [VERIFIED]

*Source*: The symlink target `/srv/df-bonsai/releases/df-53.15-steam-23622201_dfhack-53.15-r2` explicitly contains these version identifiers. This was observed in the `bridge-primitives.md` note content read from the trace.

## Installation Layout [VERIFIED]
The active installation is managed via a symbolic link:
- **Symlink**: `/srv/df-bonsai/current`
- **Target**: `/srv/df-bonsai/releases/df-53.15-steam-23622201_dfhack-53.15-r2`

This structure allows for atomic updates by changing the symlink target without modifying the running environment's path references.

## Key Components [VERIFIED]
The following components were identified via `ls /srv/df-bonsai/current/` and subsequent file reads:

### Executables & Launchers
- **`dwarfort`**: The main Dwarf Fortress executable binary.
- **`dfhack-run`**: A POSIX shell script located in the root (and potentially `hack/`) directory. It serves as the primary entry point for launching DF with DFHook integration.
- **`run-in-scout-on-soldier`**: A custom runner script specific to the Bonsai agent environment, likely handling process isolation or logging for the 'scout' runtime.
- **`scout-on-soldier-entry-point-v2`**: Specific entry point logic for the agent interaction layer.

### Libraries & Hooks
- **`libdfhooks.so`**: The core DFHack hooking library. Essential for intercepting game functions.
- **`libg_src_lib.so`**: Game source library wrapper.
- **`liblua53.so`**: Lua 5.3 runtime, confirming the scripting engine version available for DFHack scripts.
- **`libfmod*.so`**: Audio libraries (FMOD).
- **`liballegro*.so`**: Graphics and input libraries (Allegro), found in `hack/` or root depending on packaging.

### Configuration & Data
- **`dfhooks_dfhack.ini`**: Configuration file for DFHooks. Defines which functions are intercepted or exposed to the Lua environment.
- **`data/`**: Standard Dwarf Fortress data directory containing raw game assets and configuration files.
- **`VERSIONS.txt`**: Contains metadata:
  - Depot Version: `1.0.20260618.246542`
  - Runtime Version: `scout 1.0.20260618.246542`
  - Scripts Version: `0.20260618.0`

## Implications for Reset/Observe/Act/Advance

### Reset [INFERRED]
Resetting the game state likely involves:
1. Terminating the `dwarfort` process.
2. Clearing or rotating save files in the `data/Saves/` directory (if applicable).
3. Re-invoking `dfhack-run` to start a fresh instance with hooks loaded.
*Uncertainty*: The exact command sequence for a clean reset is not explicitly defined in the file listing. [OPEN]

### Observe [VERIFIED]
Observation is mediated through DFHack's Lua API:
- The presence of `liblua53.so` and `libdfhooks.so` confirms that standard DFHack observation commands (e.g., `df.global`, `df.hack`) are available.
- Scripts can be loaded via `dfhooks_dfhack.ini` or executed directly through the DFHack console interface exposed by `dfhack-run`.

### Act/Advance [INFERRED]
Actions are performed via:
1. **DFHack Commands**: Sending commands to the DFHack interpreter.
2. **Lua Scripts**: Executing custom Lua scripts that manipulate game state or input.
3. **Input Simulation**: Potentially using Allegro libraries for direct input simulation, though DFHack's higher-level APIs are preferred.

## Coding Recommendations
1. **Path Resolution**: Always resolve `/srv/df-bonsai/current` to its target before accessing files to ensure consistency during updates.
2. **Hook Configuration**: Validate `dfhooks_dfhack.ini` contents before launching to ensure required hooks are active.
3. **Version Checking**: Implement runtime version checks using DFHack's built-in mechanisms rather than relying solely on `VERSIONS.txt`, as the depot version string is non-standard.
4. **Script Loading**: Use `dfhack-run` arguments or environment variables to inject initial Lua scripts for observation setup.
5. **Next Steps**: Inspect the content of `dfhack-run` and `scout-on-soldier-entry-point-v2` to determine specific command-line flags for headless operation and logging. [OPEN]
---
