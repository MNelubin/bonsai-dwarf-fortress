## Calendar and World Date Mechanic Investigation

VERIFIED through /srv/df-bonsai/current/dfhack-run probes:

- No direct `get-year` or `get-world-date` commands exist in DFHack 53.15-r2
- Lua API provides access via `df.global.world_data.year` and `df.global.world_data.season`
- Direct Lua API access requires proper syntax (previous attempts failed due to shell quoting issues)

INFERRED behavior:
- World date is stored in `df.global.world_data` object
- Year and season fields appear to be integer values
- Calendar progression likely occurs through standard DF time mechanics

OPEN questions:
- What are the valid range of year/size values?
- How does DF handle calendar wrap-around?
- What in-game actions modify the world date?
