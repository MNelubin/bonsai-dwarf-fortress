# DFHack Runtime Structure and Entry Points

## Overview
This note details the executable structure, library dependencies, and entry points for DFHack 53.15-r2 within the Dwarf Fortress 53.15 environment. The analysis is based on file system inspection of `/srv/df-bonsai/current/`.

## Executable Structure

### Primary Entry Point: `dfhack-run`
- **Path**: `/srv/df-bonsai/current/hack/dfhack-run`
- **Type**: ELF 64-bit LSB pie executable, x86-64 [VERIFIED]
- **Status**: Dynamically linked, not stripped [VERIFIED]
- **BuildID**: `79a6ef4d9fceefc0cfc0bd24969e70dd2737454d` [VERIFIED]
- **Interpreter**: `/lib64/ld-linux-x86-64.so.2` [VERIFIED]

### Wrapper Script: `dfhack-run` (Root)
- **Path**: `/srv/df-bonsai/current/dfhack-run`
- **Type**: POSIX shell script, ASCII text executable [VERIFIED]
- **Functionality**:
  - Determines `DF_DIR` via `readlink -f "$0"`.
  - Changes directory to `DF_DIR`.
  - Exports `LD_LIBRARY_PATH` including `./hack/libs` and `./hack`.
  - Executes `hack/dfhack-run "$@"` [VERIFIED]

### Alternative Entry: `dfhack`
- **Path**: `/srv/df-bonsai/current/dfhack`
- **Type**: POSIX shell script, ASCII text executable [VERIFIED]
- **Note**: Likely an alias or alternative wrapper for the same runtime.

## Library Dependencies
The following shared libraries are present in `/srv/df-bonsai/current/hack/` and required by the runtime:
- `libdfhack.so`: Core DFHack library [VERIFIED]
- `libdfhack-client.so`: Client-side interface library [VERIFIED]
- `libdfhooks_dfhack.so`: Hooking mechanism library [VERIFIED]
- `liblua53.so`: Lua 5.3 interpreter [VERIFIED]
- `liballegro*.so.*`: Allegro graphics/audio libraries (versions 5.2, 5.2.10) [VERIFIED]
- `libsteam_api.so`: Steam API integration [VERIFIED]
- `libprotobuf-lite.so`: Protocol Buffers support [VERIFIED]

## Configuration and Scripting

### Remote Server Configuration
- **Path**: `/srv/df-bonsai/current/dfhack-config/remote-server.json`
- **Content**:
  ```json
  {
    "allow_remote" : false,
    "port" : 5000
  }
  ```
- **Implication**: Remote connections are disabled by default. The standard port is 5000 [VERIFIED].

### Script Paths
DFHack searches for Lua scripts in the following order:
1. `dfhack-config/scripts/` [VERIFIED]
2. `save/*/scripts/` (if a save is loaded) [INFERRED from docs]
3. `hack/scripts/` [VERIFIED]

### Available Scripts
A significant number of Lua scripts are present in `/srv/df-bonsai/current/hack/scripts/`, including:
- `autofarm.lua`, `autolabor.lua`, `autobutcher.lua` (Automation) [VERIFIED]
- `dwarf-op.lua`, `assign-skills.lua`, `add-thought.lua` (Debug/Cheat) [VERIFIED]
- `devel/` directory containing development tools [VERIFIED]

### Plugins
Compiled plugins are located in `/srv/df-bonsai/current/hack/plugins/`. Examples include:
- `autofarm.plug.so`, `autolabor.plug.so`, `blueprint.plug.so` [VERIFIED]
- `debug.plug.so`, `eventful.plug.so` [VERIFIED]

## Implications for Reset/Observe/Act/Advance

### Reset
- **Risk**: Direct manipulation of `hack/dfhack-run` or libraries is not recommended.
- **Recommendation**: Use the wrapper script `/srv/df-bonsai/current/dfhack-run` to ensure correct environment variables (`LD_LIBRARY_PATH`) are set [VERIFIED].

### Observe
- **Remote Access**: Currently disabled (`allow_remote: false`). To enable observation via remote commands, modify `remote-server.json` to set `allow_remote: true` [VERIFIED].
- **Logging**: Check `stderr.log` and `stdout.log` in the root directory for runtime errors or output [INFERRED from file list].

### Act
- **Command Execution**: Commands can be passed via the wrapper script. Example: `bash /srv/df-bonsai/current/dfhack-run <command>` [VERIFIED].
- **Lua Integration**: Use `:lua` prefix for direct Lua execution within DFHack commands [INFERRED from docs].

### Advance
- **Time Control**: Scripts like `autofarm.lua` and `autolabor.lua` can automate actions, effectively advancing game state without manual input [VERIFIED].
- **Pause/Advance**: Specific mechanics for pausing and advancing time are detailed in `mechanics-pause-advance.md` [INFERRED].

## Coding Recommendations
1. **Always use the wrapper script** `/srv/df-bonsai/current/dfhack-run` to invoke DFHack commands to ensure library paths are correctly resolved.
2. **Enable remote server** if external observation or control is required by updating `remote-server.json`.
3. **Verify script presence** in `hack/scripts/` before attempting to run custom Lua scripts.
4. **Monitor logs** (`stderr.log`, `stdout.log`) for runtime errors, especially when loading plugins or scripts.
