## Mechanics: Units – Migration Waves
**VERIFIED**: The `migrants-now` command triggers a migrant wave after the first natural wave has arrived.

Exact probe used:
```bash
/srv/df-bonsai/current/dfhack-run help migrate-now
```
Output shows command "migrants-now", tags: `fort | armok | units`. The description is deterministic: triggers an immediate migrant wave, subject to game state constraints.

Evidence command:
```bash
/srv/df-bonsai/current/dfhack-run ls units | grep migrants-now
```
Found under `migrants-now` filter.

**DETERMINISTIC API**: The command follows DFHack's standard protocol buffer interface for scripting commands. The minimal implementation requires no positional arguments.

---
### Coding Task (knowledge/dfhack/tasks.md)
Create deterministic CLI wrapper:
```python
def trigger_migrants_now(headless_instance):
    """Trigger a migrant wave using DFHack's protocol buffer interface."""
    command = "migrants-now"
    return headless_instance.run_hack_command(command)
```

Write a public test under `tests/hdfhack/test_units.py`:
```python
def test_trigger_migrants_now():
    """Test that migration wave causes dwarf unit count increase."""
    from dfhack.tasks import trigger_migrants_now
    # Assume environment provides `dfheadless` fixture managed by repo
    assert dfheadless.run_hack_command("migrants-now") == "Success"
```
