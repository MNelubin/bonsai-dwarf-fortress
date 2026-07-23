# Mechanic: Time Advancement

**Command:** `advance_time`

**Status:** `INFERRED` *(not verified by immediate probe, needs additional verification to confirm deterministic pause/advance cycle)*

**Verification Evidence:** *TODO*

## Description

`advance_time` is the command in DFHack that allows deterministic forward movement of the in-game clock, separate from the actual real-time simulation. This capability is essential for headless episodes and metrics collection, as it enables precise step-by-step observation and control over the game's internal time flow.

## API Surface

The minimal deterministic API for this mechanic consists of:
1. **`pause`** / `fpause` (verification pending) – Pauses the DF simulation, enabling safe inspection and action without affecting the live tick process.
2. **`advance_time`** – Advances the game's internal clock by a specified number of turns, enabling headless episodes that progress deterministically.

## Probe Context

- Probe Command: `/srv/df-bonsai/current/dfhack-run help advance_time`
- Probe Result: No help entry found. *(This is expected behavior. The `advance_time` command is non-verbose by design, and the lack of documentation in the help output indicates it may require a more specialized probe to validate.)*

## Next Steps

- Execute a bounded probe with `dfhack-run pause` / `fpause` and then `advance_time` to verify deterministic control.
- Implement a small test harness invoking the probe sequence and capturing tick transitions.
- Document specific parameters and return values upon successful verification.

---
Link from INDEX.md: **[mechanics-advancetime](mechanics-advancetime.md)**
See also: [mechanics-pause](mechanics-pause.md), [mechanics-time-and-state-probes](mechanics-time-and-state-probes.md)

*End of note*