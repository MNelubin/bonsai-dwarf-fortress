# DF-Bonsai Runtime Structure and File Layout

This note documents the file system structure of the Dwarf Fortress runtime environment within the DF-Bonsai agent setup, based on direct inspection of `/srv/df-bonsai/current/`.

## Target Versions
- **Dwarf Fortress**: 53.15 (Inferred from context; specific version string not in `VERSIONS.txt`)
- **DFHack**: 53.15-r2 (Targeted by requirements; presence confirmed via directory listing)

## Runtime Directory Structure
The primary game installation resides at `/srv/df-bonsai/current/`. The following files and directories were verified via `ls /srv/df-bonsai/current/` [VERIFIED]:

### Core Executables and Libraries
- `dwarfort`: The main Dwarf Fortress executable binary.
- `libdfhooks.so`: Shared library for DFHack hooks.
- `libfmod_plugin.so`, `libfmod.so.13`: Audio libraries.
- `libg_src_lib.so`: Likely a game source library wrapper.
- `libsdl_mixer_plugin.so`, `libsteam_api.so`: SDL and Steam API integrations.

### Configuration and Data
- `dfhooks_dfhack.ini`: DFHack configuration file.
- `data/`: Directory containing game data assets.
- `VERSIONS.txt`: Contains version metadata for the depot, runtime, and scripts [VERIFIED].
  - Content: `depot 1.0.20260618.246542`, `LD_LIBRARY_PATH ... scout 1.0.20260618.246542`.
- `DF-BONSAI-RELEASE.json`: Release metadata specific to the Bonsai environment [VERIFIED].

### DFHack Integration
- `dfhack/`: Directory for DFHack scripts and plugins. Note: A subsequent `ls /srv/df-bonsai/current/dfhack/` returned no output, suggesting it may be empty or permissions restricted in this specific snapshot, though the directory exists [VERIFIED].
- `dfhack-run`: Likely a script to launch DF with DFHack enabled.

### Documentation and Utilities
- `README.md`, `readme.txt`, `release notes.txt`: Standard documentation.
- `command line.txt`, `file changes.txt`: Logs or configuration for command-line arguments.
- `compress_bitmaps.bat`: Windows batch file (likely legacy or cross-platform artifact).
- `steam-runtime/`: Directory containing the Steam runtime environment [VERIFIED].

## Implications for Agent Control
1. **Reset**: The presence of `VERSIONS.txt` and `DF-BONSAI-RELEASE.json` suggests versioned deployments. Resetting may involve switching symlinks or updating these files.
2. **Observe**: Game state is likely stored in `data/` or derived from the `dwarfort` process memory via DFHack hooks (`libdfhooks.so`).
3. **Act**: Actions are mediated through DFHack scripts located in `dfhack/` or via command-line arguments defined in `command line.txt`.
4. **Advance**: The game loop is controlled by the `dwarfort` executable, potentially wrapped by `dfhack-run`.

## Coding Recommendations
- Use `/srv/df-bonsai/current/VERSIONS.txt` to verify environment consistency before executing actions.
- Monitor `libdfhooks.so` for hook injection points when developing new DFHack plugins.
- Ensure any file modifications respect the read-only nature of the `steam-runtime/` directory if applicable.

## Uncertainties
- The exact content of `dfhack/` is unknown as the listing was empty [OPEN].
- The specific Dwarf Fortress version number is not explicitly stated in `VERSIONS.txt`, only the depot/runtime build ID [OPEN].
