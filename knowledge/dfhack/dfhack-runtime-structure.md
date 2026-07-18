# DFHack Runtime Structure and Entry Points

This note documents the specific runtime structure of the DFHack installation within the Bonsai agent environment, focusing on entry points and library locations identified via filesystem inspection.

## Target Versions
- **Dwarf Fortress**: 53.15 [VERIFIED]
- **DFHack**: 53.15-r2 [VERIFIED]

## Filesystem Analysis
The primary game directory is located at `/srv/df-bonsai/current/`. Inspection via `ls` reveals the following key components relevant to DFHack integration:

### Entry Point Script
- **Path**: `/srv/df-bonsai/current/dfhack`
- **Type**: POSIX shell script, ASCII text executable [VERIFIED]
- **Source**: Identified via `file /srv/df-bonsai/current/dfhack` command output.
- **Implication**: This is the primary entry point for launching DFHack. It likely handles environment setup and injection of libraries before executing the main game binary.

### Library Injection
- **Path**: `/srv/df-bonsai/current/libdfhooks.so`
- **Type**: Shared Object Library [VERIFIED]
- **Source**: Identified via `ls /srv/df-bonsai/current/` command output.
- **Implication**: This library is likely injected into the Dwarf Fortress process to enable DFHook functionality. The presence of `dfhooks_dfhack.ini` further supports this configuration.

### DFHack Directory Structure
- **Path**: `/srv/df-bonsai/current/hack/`
- **Type**: Directory [VERIFIED]
- **Source**: Identified via `ls /srv/df-bonsai/current/` command output.
- **Implication**: Contains DFHack scripts and libraries. Previous verification notes indicate this directory contains `libdfhack.so` and `liblua53.so`.

### Configuration Files
- **Path**: `/srv/df-bonsai/current/dfhooks_dfhack.ini`
- **Type**: Configuration File [VERIFIED]
- **Source**: Identified via `ls /srv/df-bonsai/current/` command output.
- **Implication**: Configures the behavior of the DFHook injection layer.

## Implications for Agent Actions

1. **Reset**: To reset the environment, the agent should likely execute the `/srv/df-bonsai/current/dfhack` script or restart the `dwarfort` process with appropriate library injection settings defined in `dfhooks_dfhack.ini`. [INFERRED]
2. **Observe**: Observation should rely on DFHack Lua scripts querying game state, as screen scraping is not viable in headless TEXT mode. The `hack/` directory provides access to necessary scripting libraries. [VERIFIED]
3. **Act**: Actions can be performed by invoking DFHack commands through the Lua interface available via the `hack/` directory. The `dfhack` shell script may also provide a command-line interface for direct interaction. [INFERRED]
4. **Advance**: Time advancement mechanisms are not explicitly detailed in the filesystem structure. Further investigation into DFHack's time manipulation capabilities within version 53.15-r2 is required. [OPEN]

## Coding Recommendations
- Utilize `/srv/df-bonsai/current/dfhack` as the primary entry point for launching or interacting with the DFHack environment.
- Inspect `dfhooks_dfhack.ini` to understand current injection configurations and modify if necessary for specific automation tasks.
- Leverage Lua scripts within the `hack/` directory for complex game state queries and actions, ensuring compatibility with DFHack 53.15-r2.
- Verify the contents of the `dfhack` shell script to understand any pre-execution environment setup steps.
