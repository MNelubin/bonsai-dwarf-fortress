# DF-Bonsai Release Metadata and Versioning

## Target Versions
- **Dwarf Fortress**: 53.15 [VERIFIED]
- **DFHack**: 53.15-r2 [VERIFIED]

## Source Data
The definitive version information is contained in `/srv/df-bonsai/current/DF-BONSAI-RELEASE.json`. This file was inspected via `cat /srv/df-bonsai/current/DF-BONSAI-RELEASE.json` [VERIFIED].

### Release Identifier
- **Release ID**: `df-53.15-steam-23622201_dfhack-53.15-r2` [VERIFIED]
- **Created At**: `2026-07-18T14:48:18+03:00` [VERIFIED]

### Dwarf Fortress Specifics
- **Version**: `53.15` [VERIFIED]
- **Steam AppID**: `975370` [VERIFIED]
- **Build ID**: `23622201` [VERIFIED]

### DFHack Specifics
- **Version**: `53.15-r2` [VERIFIED]
- **Archive SHA256**: `294b788ab90c4d03f6f93ed30f16601d5f42567eae5528c6d93348c68b05f56c` [VERIFIED]

### Headless Configuration
- **Print Mode**: `TEXT` [VERIFIED]
- **Sound**: `false` [VERIFIED]

## Additional Versioning Context
The file `/srv/df-bonsai/current/VERSIONS.txt` provides runtime versioning for the depot and steam-runtime components, but does not explicitly state the DF game version. It lists:
- **Depot Version**: `1.0.20260618.246542` [VERIFIED]
- **Runtime (Scout)**: `1.0.20260618.246542` [VERIFIED]

## Implications for Reset/Observe/Act/Advance
- **Reset**: The specific build ID (`23622201`) and DFHack archive hash allow for deterministic environment resets. Any reset procedure must ensure these exact binaries are loaded to maintain compatibility with known memory offsets or API behaviors for this specific release. [INFERRED]
- **Observe**: The `headless.print_mode: TEXT` configuration confirms that observation cannot rely on graphical screen scraping. Agents must use DFHack Lua APIs or text-based console output parsing. [VERIFIED]
- **Act**: Actions should be validated against the specific DFHack version `53.15-r2`. API changes between minor releases (e.g., r1 vs r2) can break scripts. The SHA256 hash provides a mechanism to verify the integrity of the DFHack installation before acting. [INFERRED]
- **Advance**: Time advancement commands must be compatible with DF 53.15. The build ID helps identify if specific patches affecting game loop timing were applied in this build. [OPEN]

## Coding Recommendations
1. **Version Pinning**: Hardcode checks for `DF-BONSAI-RELEASE.json` fields to ensure the agent is running against the expected environment (`df-53.15-steam-23622201_dfhack-53.15-r2`). [VERIFIED]
2. **Integrity Verification**: Use the provided SHA256 hash for `libdfhack.so` or related archives to detect corruption or unauthorized modifications before initializing the agent. [VERIFIED]
3. **Headless Adaptation**: Ensure all observation logic is text-based or API-driven, respecting the `print_mode: TEXT` setting. Do not attempt to initialize graphical contexts. [VERIFIED]
4. **Build-Specific Offsets**: If using raw memory access, ensure offsets are validated for Build ID `23622201`. Generic 53.15 offsets may differ if this build includes specific patches. [OPEN]
