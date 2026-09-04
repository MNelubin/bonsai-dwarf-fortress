# Mechanics: Time Advancement

## Status
- `fpause`: VERIFIED via `/dfhack-run ls --dev fpause`
- `advance`: OPEN - no help entry found in initial probes

## Probe Evidence
1. VERIFIED: `fpause` pauses the game (tags: dfhack)
   - Command: `/dfhack-run ls --dev fpause`
   - Result: `[{"command": "fpause", "description": "Forces DF to pause", "tags": ["dfhack"]}]`
2. OPEN: `advance` not found in help/ls output
   - Command: `/dfhack-run help advance`
   - Result: Empty output (command may exist but lack documentation)

## Next Steps
Create smallest deterministic API for pausing/resuming with test cases