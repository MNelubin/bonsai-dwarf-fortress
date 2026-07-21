# Pause and Advancement Mechanic

## Verified Discoveries
- `fpause`: Forces Dwarf Fortress to pause (verified via DFHack help output)
- `advance`: Available for time progression control (found in time-progression tag)

## INFERRED
- No dedicated `pause` command exists, only `fpause` (from absence of pause in help output)

## OPEN
- Granular control over game speed and tick management (no specific commands documented yet)

### Evidence
```bash
BONSAI_PROBE_RESULT
/srv/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- dfhack-run help time-progression
```