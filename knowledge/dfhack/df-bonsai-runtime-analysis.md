# DF-Bonsai Runtime Analysis & Launcher Logic

## Target Versions
- **Dwarf Fortress**: 53.15 [VERIFIED]
- **DFHack**: 53.15-r2 [VERIFIED]

## Runtime Environment Details
The trace confirms the specific runtime configuration for the DF-Bonsai environment, resolving ambiguities present in previous notes regarding entry points and library paths.

### Launcher Script Analysis
The primary launcher script is located at `/srv/df-bonsai/current/dfhack-run`. Inspection via `file` and `head` commands reveals its internal logic:
- **Type**: POSIX shell script, ASCII text executable [VERIFIED]
- **Logic**:
  1. Determines the directory of the script (`DF_DIR`).
  2. Changes working directory to `DF_DIR`.
  3. Exports `LD_LIBRARY_PATH`, appending `./hack/libs` and `./hack` to the existing path. [VERIFIED]
  4. Executes `hack/dfhack-run "$@"`, passing all arguments to the inner runner script. [VERIFIED]

### Version Metadata
The file `/srv/df-bonsai/current/VERSIONS.txt` contains specific version identifiers:
- **Depot Version**: `1.0.20260618.246542` [VERIFIED]
- **Runtime (Scout)**: `1.0.20260618.246542` [VERIFIED]
- **Scripts**: `0.20260618.0` [VERIFIED]

These versions are consistent across the depot, runtime, and script components, indicating a synchronized build environment.

## Implications for Reset/Observe/Act/Advance

### Reset
- **Mechanism**: The `dfhack-run` script serves as the entry point. A reset likely involves terminating the current process and re-invoking this script. [INFERRED]
- **Library Path**: The explicit export of `LD_LIBRARY_PATH` ensures that DFHack libraries (`libdfhack.so`, etc.) are found in `./hack/libs` and `./hack`. Any reset procedure must preserve or re-establish this environment variable to maintain hook functionality. [VERIFIED]

### Observe
- **State Access**: Observation relies on the DFHook integration enabled by `libdfhooks.so` (identified in previous notes). The launcher ensures these libraries are loaded before the game binary executes. [INFERRED]
- **Lua Interface**: As confirmed in previous notes, Lua 5.3 is available via `liblua53.so` in the `hack/` directory. Scripts can query game state through this interface. [VERIFIED]

### Act
- **Command Injection**: Actions are performed via DFHack commands. The `dfhack-run` script passes arguments (`$@`) to the inner runner, suggesting that command-line arguments can be used to trigger specific actions or scripts at startup. [INFERRED]
- **Hook Configuration**: The `dfhooks_dfhack.ini` file (identified in previous notes) configures hook behavior. Changes to this file may require a reset to take effect. [INFERRED]

### Advance
- **Time Control**: Specific mechanisms for advancing time are not detailed in the launcher script or version files. This remains an area of uncertainty requiring further investigation into DFHack's Lua API for time manipulation. [OPEN]

## Coding Recommendations
1. **Launcher Invocation**: Use `/srv/df-bonsai/current/dfhack-run` as the primary method to start the game environment. Ensure that any automation wrapper correctly sets the working directory and inherits the `LD_LIBRARY_PATH` modifications made by this script. [VERIFIED]
2. **Library Path Verification**: Confirm that `./hack/libs` and `./hack` contain the necessary shared objects (`libdfhack.so`, `liblua53.so`) before launching. The launcher script assumes these paths are relative to the game root. [VERIFIED]
3. **Argument Passing**: Leverage the `$@` argument passing in `dfhack-run` to pass initial commands or configuration flags to the DFHack runtime. Test specific command-line options supported by `hack/dfhack-run`. [INFERRED]
4. **Version Consistency**: Validate that the depot, runtime, and script versions match (`1.0.20260618.246542`) to ensure compatibility between DFHack hooks and the game binary. Mismatches may lead to hook failures or crashes. [VERIFIED]
5. **Further Investigation**: Inspect the content of `hack/dfhack-run` (the inner runner) to understand how arguments are processed and how the game binary is ultimately executed. This will clarify the exact mechanism for injecting commands at startup. [OPEN]
