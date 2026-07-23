# Pause and Advancement Mechanic Discovery

## Verified pause command (`fpause`)
- `dfhack-run help` shows `fpause` exists under `fort` tag.
- `tags` output confirms `fpause` under `fort` tag.
**VERIFIED**: DFHack supports forcing the game to pause.

## Missing deterministic advance API
- `dfhack-run help advance` returns no entry.
- `dfhack-run ls advance` yields no commands.
- No `advance` command present in `tags` listing.
**OPEN**: No verified DFHack command to manually advance time after a pause.

### Suggested smallest deterministic implementation
- Create a Lua script `advance_by_day` that increments the game tick by one day.
- Expose via DFHack command `advance` for headless episodes.
- Write corresponding test `advance_day_test.lua` using `dfhack_run`.

#### Evidence commands
1. `/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- /srv/df-bonsai/current/dfhack-run help calendar`
2. `/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- /srv/df-bonsai/current/dfhack-run help time`
3. `/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- /srv/df-bonsai/current/dfhack-run ls units`
4. `/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- /srv/df-bonsai/current/dfhack-run help advance`
5. `/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- /srv/df-bonsai/current/dfhack-run tags`