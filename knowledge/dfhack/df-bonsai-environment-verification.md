# DF-Bonsai Environment Verification

## Target Versions
- **Dwarf Fortress**: 53.15 (Inferred from project context; `VERSIONS.txt` shows depot version `1.0.20260618.246542` [VERIFIED])
- **DFHack**: 53.15-r2 (Inferred from project context; no explicit version string found in trace) [OPEN]

## Environment Structure
The DF-Bonsai environment is located at `/srv/df-bonsai/current/`. The directory structure reveals a standard Linux-based DF installation with DFHack integration.

### Key Directories and Files
- **Root**: `/srv/df-bonsai/current/` contains the main game executable `dwarfort`, configuration files (`dfhooks_dfhack.ini`), and libraries (`libdfhooks.so`, `libfmod*.so`). [VERIFIED]
- **DFHack Directory**: `/srv/df-bonsai/current/hack/` contains DFHack-specific components:
  - `dfhack-run`: A POSIX shell script executable used to launch DF with DFHook integration. [VERIFIED]
  - Libraries: `libdfhack.so`, `libdfhack-client.so`, `libdfhooks_dfhack.so`, and Lua runtime `liblua53.so`. [VERIFIED]
  - Allegro libraries: Various `liballegro*.so` files indicating the game's dependency on the Allegro library for graphics/input. [VERIFIED]
- **Versioning**: `/srv/df-bonsai/current/VERSIONS.txt` lists depot version `1.0.20260618.246542` and runtime version `scout 1.0.20260618.246542`. This suggests a specific build or snapshot of the game/DFHack environment. [VERIFIED]

## Implications for Reset/Observe/Act/Advance
- **Reset**: The presence of `dfhack-run` and `libdfhooks.so` implies that DFHack is loaded via dynamic linking at startup. A reset likely involves restarting the `dwarfort` process with these hooks. [INFERRED]
- **Observe**: DFHack provides Lua-based observation capabilities. The `liblua53.so` confirms Lua 5.3 support, which is standard for DFHack scripting. [VERIFIED]
- **Act/Advance**: Actions are likely mediated through DFHack commands or direct memory manipulation via the hooks. The `dfhooks_dfhack.ini` configuration file may define hook behaviors. [INFERRED]

## Coding Recommendations
1. **Version Verification**: Explicitly verify DF and DFHack versions at runtime using DFHack's built-in version checking mechanisms, as `VERSIONS.txt` does not explicitly state "53.15". [OPEN]
2. **Hook Initialization**: Ensure `dfhooks_dfhack.ini` is correctly configured for the target environment before launching `dwarfort`. [INFERRED]
3. **Lua Scripting**: Leverage Lua 5.3 features available in `liblua53.so` for observation and control scripts. [VERIFIED]
4. **Library Dependencies**: Confirm all Allegro and DFHack libraries are present and compatible with the target OS to avoid runtime errors. [VERIFIED]
