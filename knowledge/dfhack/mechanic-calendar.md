## Mechanic-Calendar.md

### Mechanic
Calendar/Time subsystem in Dwarf Fortress

### Tags
gameplay

### Evidence
#### DFHack `calendar` command unavailable
```bash
/sopt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- /srv/df-bonsai/current/dfhack-run help calendar
```
Output: `No help entry found for "calendar"`

**Claim**: The `calendar` command is unavailable in the current DFHack version (`53.15-r2`).
**Tag**: VERIFIED (direct probe, no entry found).

#### Unauthenticated calendar via `dfhack.world.calendar`
```bash
/sopt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- /srv/df-bonsai/current/dfhack-run help world
```
Output: `dfhack.world.*` provides `calendar`, pointing to `df.global.current_year` and related tables.

**Claim**: Calendar data is accessible via Lua (`dfhack.world.calendar`), but no existing command provides a structured API.
**Tag**: VERIFIED (direct probe, explicit path to data).

### Next Step
Create a deterministic API that queries calendar data through a Lua probe with DFHack's runtime. Verify in headless mode with the wrapper.

Test: Ensure the probe returns a structured Lua table with fields `year`, `month`, `day` from `dfhack.world.calendar`.
