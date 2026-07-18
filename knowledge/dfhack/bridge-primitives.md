---
# Bridge Primitives and Game Loop Controls

## Overview
This note documents the structural components of the Dwarf Fortress bridge environment identified in `/srv/df-bonsai/current`. It focuses on entry points, library dependencies, and configuration files relevant to automation hooks.

## Installation Layout [VERIFIED]
The current installation is a symbolic link:
- **Path**: `/srv/df-bonsai/current` -> `/srv/df-bonsai/releases/df-53.15-steam-23622201_dfhack-53.15-r2`
- **Source**: `file /srv/df-bonsai/current` output in trace.

## Key Components [VERIFIED]
The following files and directories were identified via `ls /srv/df-bonsai/current/`:

### Entry Points & Scripts
- `dfhack-run`: Likely the primary launcher for DFHack-enabled sessions.
- `run-in-scout-on-soldier`: Custom runner script, possibly related to the 'scout' runtime mentioned in VERSIONS.txt.
- `scout-on-soldier-entry-point-v2`: Specific entry point logic.

### Libraries & Hooks
- `libdfhooks.so`: The core DFHack hooking library.
- `libg_src_lib.so`: Game source library wrapper.
- `dfhooks_dfhack.ini`: Configuration for DFHooks, likely defining which functions are intercepted or exposed.

### Data & Configuration
- `data/`: Standard DF data directory.
- `VERSIONS.txt`: Contains version metadata. Note: The 'depot' version is listed as `1.0.20260618.246542`, which appears to be a future-dated or internal build identifier rather than the public release date. This suggests a custom or pre-release build environment.

## Implications for Automation [INFERRED]
1. **Reset/Observe**: The presence of `dfhack-run` and `libdfhooks.so` indicates that standard DFHack Lua APIs are available. Resetting the game state likely involves invoking specific DFHack commands via this runner or manipulating the save directory structure.
2. **Act/Advance**: Game loop control is typically managed through DFHack's `dfhack` command-line interface or Lua scripts loaded via `dfhooks_dfhack.ini`. The `scout-on-soldier` scripts suggest a specialized agent interaction layer.
3. **Uncertainty [OPEN]**: The exact mechanism for 'resetting' the game state (e.g., deleting saves vs. in-game reset commands) is not explicitly detailed in the file listing. Further inspection of `dfhack-run` or `scout-on-soldier-entry-point-v2` content is required.

## Coding Recommendations
1. **Use DFHack Lua API**: Leverage `libdfhooks.so` for low-level access. Avoid direct binary manipulation.
2. **Configuration Check**: Inspect `dfhooks_dfhack.ini` to understand which hooks are active by default.
3. **Version Handling**: Account for the non-standard version string in `VERSIONS.txt` when logging or validating environment integrity.
4. **Next Steps**: Read the content of `dfhack-run` and `scout-on-soldier-entry-point-v2` to identify specific command-line arguments for game control.
