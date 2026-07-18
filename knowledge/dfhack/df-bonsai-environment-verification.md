# DF-Bonsai Environment Verification

This note documents the verified environment configuration for Dwarf Fortress and DFHack within the Bonsai agent runtime, based on filesystem inspection.

## Verified Facts

* **Target Versions**: The active installation is confirmed to be Dwarf Fortress `53.15` (Steam Build ID `23622201`) paired with DFHack `53.15-r2`. This was verified by reading `/srv/df-bonsai/current/DF-BONSAI-RELEASE.json` [VERIFIED].
* **Symlink Structure**: The path `/srv/df-bonsai/current` is a symbolic link pointing to `/srv/df-bonsai/releases/df-53.15-steam-23622201_dfhack-53.15-r2`. This was verified via `file /srv/df-bonsai/current` [VERIFIED].
* **Headless Configuration**: The release JSON indicates `headless.print_mode` is set to `TEXT` and `sound` is `false`, confirming a headless text-mode execution environment suitable for automated agents [VERIFIED].
* **DFHack Directory Structure**: The DFHack installation resides in `/srv/df-bonsai/current/hack/`. Key components verified via `ls -la` include:
    * `libdfhack.so`: The core library (18.6 MB) [VERIFIED].
    * `liblua53.so`: Lua 5.3 runtime support [VERIFIED].
    * `scripts/`, `plugins/`, `lua/`: Standard DFHack extension directories present [VERIFIED].
    * `symbols.xml`: Present, indicating debug symbol availability for this build [VERIFIED].
* **Missing Knowledge Base**: An attempt to read `/srv/bonsai-agent/runs/.../repo/knowledge` failed with "File not found", and an attempt to list a local `hack/` directory in the repo also failed. This implies the knowledge base must be initialized from scratch or is located elsewhere [VERIFIED].

## Inferred Implications

* **Stability**: The presence of specific build IDs and SHA256 hashes suggests a pinned, immutable release structure. Updates likely involve swapping the symlink target rather than modifying files in-place [INFERRED].
* **Agent Interaction**: Since `print_mode` is `TEXT`, any DFHack commands executed by the agent will output to stdout/stderr or a text buffer, not a graphical overlay. This simplifies parsing but requires careful handling of terminal escape codes if present [INFERRED].

## Open Questions

* **DFHack Initialization**: It is unclear if `dfhack-run` has been executed yet in this session. The presence of `libdfhooks.so` in the root suggests hooking capability, but active state is unknown [OPEN].
* **Plugin Availability**: While the `plugins/` directory exists, its contents were not listed. It is unknown which specific plugins (e.g., `stonesense`, `autolab`) are pre-loaded or available for use [OPEN].

## Coding Recommendations

1.  **Path Resolution**: Always resolve `/srv/df-bonsai/current` via symlink to ensure compatibility with future version swaps. Do not hardcode the release ID path.
2.  **Command Execution**: Use `dfhack-run` or direct Lua injection via `libdfhack-client.so` if available, rather than simulating keyboard input, given the headless text mode.
3.  **Error Handling**: Implement checks for the existence of `/srv/df-bonsai/current/hack/libdfhack.so` before attempting to load DFHack APIs to avoid runtime crashes.
4.  **Knowledge Initialization**: Since the local knowledge directory is missing, the agent should create `knowledge/INDEX.md` and this note file as part of its initialization routine.
