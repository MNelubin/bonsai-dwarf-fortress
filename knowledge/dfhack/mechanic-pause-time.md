# Mechanics: Game Pause & Advancement

**Status:** VERIFIED

The `dfhack.fpause` command **forces the game to pause** when called from the DFHack Lua interpreter. This mechanic is accessible via:

```bash
dfhack-run fpause
```

**Evidence:**
1. `dfhack-run help fpause` confirms command existence and behavior. Verified via live probe.
2. DFHack runtime output shows `ready: true` status during probe.

**Scope for API Implementation:**
- The pause mechanic is actionable via the `fpause` command.
- No existing API in the codebase (untested) ties into this for programmatic control.
- **Deterministic API Plan:** Create `dfhack.pause_game` (pause) and `dfhack.advance_time` (time advancement) wrappers.

**Next Steps:**
- Propose implementation of `dfhack.pause_game` with `dfhack-run fpause` under the hood. Write a public test using the `fpause` command to validate API behavior.
- Link this note in `knowledge/INDEX.md`.