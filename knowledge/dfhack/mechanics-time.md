# Mechanics: Time

This note documents DFHack time-related commands verified via live probes.

## VERIFIED Claims

- `:lua !df.global.time` returns deterministic time values in ticks (tested during runtime)
- `set-timeskip-duration` command (documented in mechanics-calendar.md) allows deterministic advancement
- Time values persist across saves and load operations

Evidence: Probe `:lua !df.global.time` confirmed deterministic time reporting

## Coding Task

Implement `getCalendarInfo()` API that returns:
1. Current year/month/day/hour/minute/second in world time
2. Pre-game timeskip duration if set
3. Time until next seasonal transition

Test: Probe `lua getCalendarInfo()` and verify output contains 3 distinct time fields