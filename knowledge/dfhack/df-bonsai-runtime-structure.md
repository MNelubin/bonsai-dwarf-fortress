---
# DF-Bonsai Runtime Structure and File Layout

## Overview
This note documents the physical file layout of the Dwarf Fortress runtime environment within the DF-Bonsai agent infrastructure. It details the directory structure, key executables, libraries, and configuration files identified in `/srv/df-bonsai/current`.

## Target Versions [VERIFIED]
Based on `DF-BONSAI-RELEASE.json`:
- **Dwarf Fortress**: 53.15 (Steam AppID: 975370, Build ID: 23622201)
- **DFHack**: 53.15-r2
- **Headless Mode**: Enabled (`print_mode`: TEXT, `sound`: false)

## Directory Structure [VERIFIED]
The root directory `/srv/df-bonsai/current` contains the following key components:

### Core Executables & Scripts
- `dwarfort`: The main Dwarf Fortress executable (34MB).
- `dfhack`: The DFHack command-line interface tool.
- `dfhack-run`: A script likely used to launch DF with DFHook integration.
- `run-in-scout-on-soldier`: Custom runner script for agent interaction.
- `scout-on-soldier-entry-point-v2`: Specific entry point logic for the scout runtime.

### Libraries & Hooks
- `libdfhooks.so`: Core DFHack hooking library (35KB).
- `libg_src_lib.so`: Game source library wrapper (1.5MB).
- `libfmod.so.13` / `libfmod_plugin.so`: Audio libraries (present but sound disabled in headless mode).
- `libsteam_api.so`: Steam API integration.
- `libsdl_mixer_plugin.so`: SDL mixer plugin.

### Configuration & Data
- `dfhooks_dfhack.ini`: DFHack configuration file (25 bytes).
- `data/`: Standard Dwarf Fortress data directory.
- `g_src/`: Game source directory.
- `hack/`: DFHack installation directory containing plugins, scripts, and Lua libraries.
- `steam-runtime/`: Steam runtime environment.

## Key Observations [VERIFIED]
1. **Symbolic Link**: `/srv/df-bonsai/current` is a symlink to the specific release directory `/srv/df-bonsai/releases/df-53.15-steam-23622201_dfhack-53.15-r2`.
2. **Headless Configuration**: The `DF-BONSAI-RELEASE.json` explicitly disables sound and sets print mode to TEXT, indicating a non-GUI execution environment.
3. **Custom Scripts**: The presence of `run-in-scout-on-soldier` and `scout-on-soldier-entry-point-v2` suggests a specialized agent interaction layer beyond standard DFHack usage.

## Implications for Automation [INFERRED]
1. **Reset/Observe**: Game state resets likely involve manipulating the save directory or invoking specific DFHack commands via `dfhack-run`. The headless mode implies observation is done through text output or API calls rather than screen scraping.
2. **Act/Advance**: Actions are likely executed via DFHack Lua scripts or command-line arguments passed to `dfhack-run`. The `scout-on-soldier` scripts may provide a higher-level abstraction for agent actions.
3. **Library Dependencies**: The presence of `libdfhooks.so` and `libg_src_lib.so` indicates that low-level game state manipulation is possible through DFHack's hooking mechanism.

## Uncertainties [OPEN]
1. **Exact Reset Mechanism**: It is unclear whether resets are performed by deleting save files, using in-game commands, or via a specific DFHack plugin. Further inspection of `dfhack-run` and `scout-on-soldier-entry-point-v2` is required.
2. **Agent Interaction Protocol**: The exact protocol for the 'scout' runtime is not detailed. It may involve custom IPC or file-based communication.
3. **Plugin Configuration**: The contents of `dfhooks_dfhack.ini` are minimal (25 bytes), but its full impact on available hooks is unknown without reading the file.

## Coding Recommendations
1. **Leverage DFHack Lua API**: Use `libdfhooks.so` for low-level access to game state. Avoid direct binary manipulation of `dwarfort`.
2. **Inspect Custom Scripts**: Read `run-in-scout-on-soldier` and `scout-on-soldier-entry-point-v2` to understand the agent interaction layer.
3. **Configuration Validation**: Verify `dfhooks_dfhack.ini` contents to ensure necessary hooks are enabled.
4. **Headless Mode Handling**: Ensure all observation logic relies on text output or API calls, not GUI elements.
5. **Version Compatibility**: Code should be compatible with DF 53.15 and DFHack 53.15-r2. Test against the specific build ID 23622201.
