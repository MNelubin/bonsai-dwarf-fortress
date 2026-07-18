# DF-Bonsai Environment Verification

This note documents the verified state of the Dwarf Fortress and DFHack installation within the Bonsai agent environment, based on filesystem inspection.

## Target Versions
The following versions are confirmed present in the runtime environment:
- **Dwarf Fortress**: 53.15 (Steam AppID: 975370, Build ID: 23622201) [VERIFIED]
- **DFHack**: 53.15-r2 [VERIFIED]

## Filesystem Structure
The primary game and hack binaries are located at `/srv/df-bonsai/current/`. Key components identified via `ls -la` include:
- `dwarfort`: The main Dwarf Fortress executable (34MB) [VERIFIED]
- `hack/`: Directory containing DFHack libraries (`libdfhack.so`, `liblua53.so`) and scripts [VERIFIED]
- `DF-BONSAI-RELEASE.json`: Metadata file confirming release details and headless configuration [VERIFIED]

## Headless Configuration
The environment is configured for headless operation:
- **Print Mode**: TEXT [VERIFIED]
- **Sound**: Disabled [VERIFIED]

## Implications for Agent Actions
1. **Reset**: The presence of `DF-BONSAI-RELEASE.json` suggests a managed deployment. Resetting the environment likely involves restarting the `dwarfort` process with DFHack injected via `libdfhooks.so`. [INFERRED]
2. **Observe**: Since print mode is TEXT, observation should rely on parsing text output or using DFHack Lua scripts to query game state directly rather than screen scraping. [VERIFIED]
3. **Act**: Actions can be performed via DFHack commands injected through the `hack/` directory interface. The presence of `liblua53.so` confirms Lua scripting support is available for automation. [VERIFIED]
4. **Advance**: Time advancement should be controlled via DFHack's time manipulation features if available in 53.15-r2, or by allowing the game to tick naturally in headless mode. [OPEN]

## Coding Recommendations
- Use the `hack/` directory structure to locate specific Lua libraries for interaction.
- Verify compatibility of DFHack commands with version 53.15-r2 before execution, as API changes may occur between minor versions.
- Utilize the `DF-BONSAI-RELEASE.json` file to programmatically verify environment integrity at runtime.
