# Mechanics: Buildings

## Probe: DFHack design tools

We ran the following command to inspect available DFHack tools:

```bash
/sopt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- /srv/df-bonsai/current/dfhack-run ls design
```

This command revealed a tag `buildings` and a tool `stockpiles` (`Import, export, or modify stockpile settings.`).

## Notes

- The `stockpiles` tool appears to be the primary interface for modifying building stockpiles in DFHack.
- No dedicated note currently exists for the building subsystem in the knowledge base.
- The presence of the `stockpiles` tool suggests a bounded, deterministic API for manipulating building stockpiles.

## Next Step

The smallest executable coding task is to implement a deterministic API wrapper around the `stockpiles` DFHack tool with subcommands `list`, `import`, and `export`, followed by a simple public test that runs the API with the `list` subcommand and asserts that the output contains JSON-formatted data with at least one stockpile setting.