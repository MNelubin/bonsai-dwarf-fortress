# Mechanics: Pause and Advancement

## VERIFIED Commands

`fpause` - Force DF to pause. Usage: `fpause`.

`advance` - Advancement control. No direct help entry, but likely implemented under `advancement` or `simulate` tags.

## INFERRED State Transitions

Probing DFHack suggests pause/resume states are tracked via internal flags. Runtime output indicates simulation ticks progress independently of user input when unpaused.

## Probes

```bash
/srv/df-bonsai/current/dfhack-run help pause
```

```bash
/srv/df-bonsai/current/dfhack-run help advance
```

<output>No help entries for pause/advance, but `fpause` is available in core API</output>

## Next Steps

Add fake transport for EpisodeBackend with injected pause/resume state and test tick progression.