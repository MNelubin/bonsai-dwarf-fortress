# Pause and Advancement Mechanics

## VERIFIED DISCOVERIES
- `fpause` command is present and works to pause the game
- `advance` command is available but behavior for granular time control is uncertain

## INFERRED MECHANISMS
- Time advancement gaps suggest potential need for intermediate time steps
- Pause state persistence after save/load not yet tested

## PROBE COMMANDS
```bash
bonsai-df-probe --timeout 30 -- dfhack-run fpause
bonsai-df-probe --timeout 30 -- dfhack-run advance 1
```

## TESTS
1. Verify `fpause` works by detecting game state pause
2. Test `advance 1` by checking time progression
3. Confirm pause state persistence across save/load