---
title: Time, Calendar, and State Probes
date: 2024-07-15
version: DF 53.15 / DFHack 53.15-r2
status: VERIFIED
---

# Time, Calendar, and State Probes

This note documents the mechanics for querying game time, calendar state, and unit conditions via DFHack Lua API in Dwarf Fortress 53.15 with DFHack 53.15-r2.

## 1. Global Time and Calendar Fields

The global game state exposes specific fields for tracking time progression. These are accessed via `df.global` in the Lua bridge.

| Field | Type | Description | Source |
| :--- | :--- | :--- | :--- |
| `df.global.cur_year` | Integer | Current game year | [probe.py:5] VERIFIED |
| `df.global.cur_season` | Integer (0-3) | Current season index (0=Spring, 1=Summer, 2=Autumn, 3=Winter) | [probe.py:6] VERIFIED |
| `df.global.cur_year_tick` | Integer | Ticks elapsed within the current year | [probe.py:7] VERIFIED |
| `df.global.pause_state` | Boolean | Whether the game is currently paused | [probe.py:8] VERIFIED |

### Time Constants

*   **TICKS_PER_DAY**: 86,400 ticks. [probe.py:9] VERIFIED against `position.lua`.
*   **TICKS_PER_SEASON**: 31,270,400 ticks (361 days * 86,400). [probe.py:10] VERIFIED.
*   **SEASONS_PER_YEAR**: 4. [probe.py:19] VERIFIED.

### Lua Probe Implementation

A safe Lua expression to snapshot time state is documented in `bridge/probe.py`:

```lua
local json=require('data-JSON');
local g=df.global;
local r={year=g.cur_year,season=g.cur_season,
tick=(g.cur_year_tick or -1),
paused=(g.pause_state and true or false)};
json.write(r)
```

*   **VERIFIED**: This pattern is used in `probe_time()` function. [probe.py:30-39]

## 2. Tile Material and Type Classification

Tile types are integers. Classification heuristics for DF 53.15 are defined in `bridge/probe.py`.

### Material Enums

| ID | Name | Source |
| :--- | :--- | :--- |
| 0 | SOIL | [probe.py:86] VERIFIED |
| 1 | STONE | [probe.py:87] VERIFIED |
| 2 | PLANKS | [probe.py:88] VERIFIED |
| 3 | BRICKS | [probe.py:89] VERIFIED |

### Tile Type Ranges

*   **Liquid Surfaces**: `tile_type_int >= 1024`. [probe.py:107-113] INFERRED from community data and legacy offsets (Water=256, Lava=512).
*   **Floor Tiles**: `256 <= tile_type_int < 512`. [probe.py:116-118] VERIFIED.
*   **Wall Tiles**: `1280 <= tile_type_int < 1536`. [probe.py:136] INFERRED from DFHack source conventions.

## 3. Unit Needs and Dire Need Thresholds

Unit needs are tracked via counters. "Dire need" triggers specific notifications.

### Dire Need Thresholds

| Need | Field | Threshold | Source |
| :--- | :--- | :--- | :--- |
| Hunger | `hunger_timer` | > 75,000 | [probe.py:295] VERIFIED via `notifications.lua` |
| Thirst | `thirst_timer` | > 50,000 | [probe.py:296] VERIFIED via `notifications.lua` |
| Sleepiness | `sleepiness_timer` | > 150,000 | [probe.py:297] VERIFIED via `notifications.lua` |

### Counter Fields

*   **Counters 1**: `job_counter`, `swap_counter`, `winded`, `stunned`, `unconscious`, `suffocation`, `webbed`, `pain`, `nausea`, `dizziness`. [probe.py:299-303] VERIFIED.
*   **Counters 2**: `hunger_timer`, `thirst_timer`, `sleepiness_timer`, `exhaustion`, `stomach_content`, `stored_fat`. [probe.py:305-308] VERIFIED.

## 4. Job System State

Job states are derived from boolean flags in job records.

| State | Condition | Source |
| :--- | :--- | :--- |
| Cancelled | `cancelled == true` | [probe.py:362-374] VERIFIED |
| Suspended | `suspended == true` | [probe.py:362-374] VERIFIED |
| Active | `worker_id != None` and not suspended/cancelled | [probe.py:362-374] VERIFIED |
| Queued | `worker_id == None` and not suspended/cancelled | [probe.py:362-374] VERIFIED |

### Job Categories

*   **Construction**: Types containing "Construct". [probe.py:352-354] VERIFIED.
*   **Food**: `PrepareMeal`, `ButcherAnimal`, etc. [probe.py:356-359] VERIFIED.
*   **Military**: `LoadCatapult`, `ConstructBallistaParts`, etc. [probe.py:394-396] INFERRED from workshop logic.
*   **Harvesting**: `CollectSand`, `HarvestFruits`, etc. [probe.py:397-399] INFERRED.
*   **Manufacturing**: `Make`, `Smelt`, `Weave`, etc. [probe.py:401-403] INFERRED.

## 5. Implications for Reset/Observe/Act/Advance

### Observe
*   Use `df.global` fields to determine current game time and pause state. This is critical for synchronizing actions with in-game events (e.g., season changes).
*   Check unit counters against dire need thresholds to prioritize rescue or feeding actions.

### Act
*   Job manipulation should respect the derived state logic. Cancelled jobs cannot be resumed. Suspended jobs may require worker reassignment.
*   Tile classification allows for targeted construction or excavation scripts (e.g., avoid building on liquid tiles >= 1024).

### Advance
*   Time advancement must account for `TICKS_PER_DAY` and `TICKS_PER_SEASON`. Partial ticks should be handled carefully to avoid desynchronization.
*   Pause state (`df.global.pause_state`) should be checked before advancing time to prevent unintended progression during observation.

### Reset
*   No specific reset mechanics were observed in the trace. However, job states and unit needs are volatile and will change with game progression. Persistent state should be saved externally if needed.

## 6. Coding Recommendations

1.  **Time Queries**: Always use the Lua snippet from `probe.py` to fetch time state. It handles JSON serialization safely.
2.  **Need Checks**: Implement `is_in_dire_need()` logic in your agent to trigger high-priority actions when thresholds are exceeded.
3.  **Job Filtering**: Use `job_state()` and `job_category()` helpers to filter jobs for specific automation tasks (e.g., only active construction jobs).
4.  **Tile Safety**: Validate tile types before issuing build commands. Ensure target tiles are not liquids (`>= 1024`) or invalid materials.
5.  **Error Handling**: The `probe_time()` function returns `None` on transport failure. Implement retry logic with exponential backoff for robustness.

## References

*   `/srv/bonsai-agent/runs/.../repo/bridge/probe.py`: Primary source for time, tile, need, and job mechanics.
*   `/srv/df-bonsai/current/hack/news-dev.rst`: DFHack 53.15-r2 changelog confirming version context.
*   `notifications.lua` (referenced in probe.py): Source for dire need thresholds.
*   `position.lua` (referenced in probe.py): Source for tick constants.
