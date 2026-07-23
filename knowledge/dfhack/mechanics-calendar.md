# Mechanics: Calendar/Time

## INFERRED UNIMPLEMENTED
- DFHack lacks a direct `calendar`, `time`, or `advance` API as evidenced by:
  - `help calendar` probe: no entry found
  - `help advance` probe: no entry found
  - Runtime status: BONSAI_PROBE_RESULT indicates ready but no time-related commands
- Needed for deterministic time advancement and episode metrics

## PROBE COMMANDS
```bash
# Calendar/time
/srv/df-bonsai/current/dfhack-run help calendar

# Advancement
/srv/df-bonsai/current/dfhack-run help advance
```