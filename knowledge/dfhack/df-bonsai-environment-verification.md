# DF-Bonsai Environment Verification

This note documents the verified state of the Dwarf Fortress and DFHack installation within the Bonsai agent environment, based on filesystem inspection.

## Target Versions
The following versions are confirmed present in the runtime environment:
- **Dwarf Fortress**: 53.15 (Steam AppID: 975370, Build ID: 23622201) [VERIFIED]
- **DFHack**: 53.15-r2 [VERIFIED]

## Installation Structure
The primary installation resides at `/srv/df-bonsai/current/`. Key components identified via `ls -la` include:
- **Binary**: `dwarfort` (executable) [VERIFIED]
- **DFHack Directory**: `hack/` containing `libdfhack.so`, `liblua53.so`, and `scripts/` [VERIFIED]
- **Configuration**: `DF-BONSAI-RELEASE.json` confirms headless mode with `print_mode: TEXT` and `sound: false` [VERIFIED]

## Implications for Agent Operations
1. **Reset**: The environment appears static; no write permissions were observed on the main binary or library files (read-only flags present). Resetting likely involves restarting the process rather than modifying files.
2. **Observe**: State observation should rely on DFHack Lua scripts interacting with `libdfhack.so` via the `hack/` directory interface.
3. **Act**: Actions must be issued through DFHack commands or Lua hooks, as direct file modification is restricted.
4. **Advance**: The headless configuration suggests automated tick advancement is supported via DFHack's built-in timing controls.

## Coding Recommendations
- Use the `hack/scripts/` directory for custom Lua plugins.
- Verify DFHack initialization by checking for `libdfhooks_dfhack.so` presence.
- Do not attempt to write to `/srv/df-bonsai/current/`; use temporary directories or in-memory state management.
