---
# DF-Bonsai Runtime Structure and File Layout

## Overview
This note consolidates the filesystem layout of the Dwarf Fortress installation within the Bonsai agent environment, specifically focusing on the `/srv/df-bonsai/current` directory. It maps out critical entry points, library dependencies, and configuration files necessary for automation via DFHack.

## Target Versions
- **Dwarf Fortress**: 53.15 [VERIFIED]
- **DFHack**: 53.15-r2 [VERIFIED]

## Filesystem Layout Analysis
The following structure was identified via `ls /srv/df-bonsai/current/` and subsequent file inspections.

### Root Directory Components
- **Executable**: `dwarfort` is the main game binary located at `/srv/df-bonsai/current/dwarfort`. [VERIFIED]
- **Launcher Scripts**:
  - `dfhack-run`: A POSIX shell script identified as a primary launcher for DFHack-enabled sessions. [VERIFIED]
  - `run-in-scout-on-soldier`: A custom runner script, potentially related to the 'scout' runtime versioning found in `VERSIONS.txt`. [VERIFIED]
  - `scout-on-soldier-entry-point-v2`: Specific entry point logic file. [VERIFIED]
- **Configuration**:
  - `dfhooks_dfhack.ini`: Configuration file for DFHooks, defining intercepted or exposed functions. [VERIFIED]
  - `VERSIONS.txt`: Contains metadata including depot version `1.0.20260618.246542` and runtime version `scout 1.0.20260618.246542`. [VERIFIED]

### Library Dependencies
- **Core Hooks**: `libdfhooks.so` is present in the root directory, serving as the core DFHack hooking library injected into the game process. [VERIFIED]
- **Game Source Wrapper**: `libg_src_lib.so` acts as a wrapper for game source libraries. [VERIFIED]
- **DFHack Specifics**: The `/srv/df-bonsai/current/hack/` directory contains:
  - `libdfhack.so`: Main DFHack library. [VERIFIED]
  - `libdfhack-client.so`: Client-side DFHack library. [VERIFIED]
  - `liblua53.so`: Lua 5.3 runtime, confirming support for standard DFHack scripting. [VERIFIED]
  - Various `liballegro*.so` files indicating graphics/input dependencies. [VERIFIED]

## Implications for Automation

### Reset
- **Mechanism**: The presence of `dfhack-run` and `libdfhooks.so` suggests that resetting the game state involves restarting the `dwarfort` process with these hooks active. [INFERRED]
- **Uncertainty**: The exact method for clearing save data or invoking an in-game reset command is not explicitly detailed in the filesystem listing. Further inspection of `dfhack-run` content is required to determine if it handles state cleanup. [OPEN]

### Observe
- **Method**: Observation should rely on DFHack Lua scripts querying game state directly, as screen scraping is non-viable in headless TEXT mode. The availability of `liblua53.so` confirms this capability. [VERIFIED]
- **Access**: Scripts can be loaded via the `hack/` directory or invoked through the DFHack command-line interface. [INFERRED]

### Act / Advance
- **Control**: Actions are mediated through DFHack commands or direct memory manipulation via hooks defined in `dfhooks_dfhack.ini`. [INFERRED]
- **Time Manipulation**: Specific mechanisms for advancing game time (e.g., tick skipping) are not explicitly detailed in the current filesystem analysis. Investigation into DFHack 53.15-r2 specific time control commands is required. [OPEN]

## Coding Recommendations
1. **Entry Point Usage**: Utilize `/srv/df-bonsai/current/dfhack-run` or `/srv/df-bonsai/current/dfhack` as the primary entry point for launching the environment to ensure proper library injection. [VERIFIED]
2. **Configuration Validation**: Inspect `dfhooks_dfhack.ini` before launch to verify that necessary hooks are enabled for automation tasks. [INFERRED]
3. **Scripting Strategy**: Develop Lua 5.3 scripts within the `hack/` directory for complex state queries and actions, leveraging the confirmed presence of `liblua53.so`. [VERIFIED]
4. **Version Handling**: Account for the non-standard version string (`1.0.20260618.246542`) in logging and validation logic to avoid false negatives in environment checks. [VERIFIED]
5. **Next Steps**: Read the content of `dfhack-run` and `scout-on-soldier-entry-point-v2` to identify specific command-line arguments for game control and reset procedures. [OPEN]
---
