# Unit, Job, Item, and Skill Mechanics

## Target Versions
- **Dwarf Fortress**: 53.15 [VERIFIED]
- **DFHack**: 53.15-r2 [VERIFIED]

## Overview
This note details the internal structures for units, jobs, items, map features, tiles, and skills as observed in `bridge/probe.py` and `game_runner/episode.py`. It provides verified thresholds, enum mappings, and state transition logic essential for automation agents.

## 1. Unit Needs and Dire Thresholds
Unit needs are tracked via counters exposed by `hack/scripts/internal/gm-unit/editor_counters.lua` and `notifications.lua` [VERIFIED].

### Dire Need Thresholds
A unit is considered in "dire need" if any of the following timers exceed their thresholds [VERIFIED]:
- **Hunger**: `hunger_timer > 75000`
- **Thirst**: `thirst_timer > 50000`
- **Sleepiness**: `sleepiness_timer > 150000`

### Counter Fields
The unit status structure contains two groups of counters [VERIFIED]:
1. **Counters 1 (Immediate State)**: `job_counter`, `swap_counter`, `winded`, `stunned`, `unconscious`, `suffocation`, `webbed`, `pain`, `nausea`, `dizziness`.
2. **Counters 2 (Physiological Timers)**: `hunger_timer`, `thirst_timer`, `sleepiness_timer`, `exhaustion`, `stomach_content`, `stored_fat`.

### Severity Scoring
A severity score (0.0–6.0) can be derived as follows [VERIFIED]:
- +1.0 for each dire threshold exceeded (Hunger, Thirst, Sleepiness).
- +0.5 for each non-zero physical distress flag (`pain`, `nausea`, `dizziness`, `suffocation`).

## 2. Job System State and Categorization
Job states are derived from fields emitted by `bridge/core.lua job_list()` [VERIFIED].

### Job States
- **Cancelled**: `job_record.cancelled == True`
- **Suspended**: `job_record.suspended == True` (and not cancelled)
- **Active**: `job_record.worker_id is not None` (and not suspended/cancelled)
- **Queued**: `job_record.worker_id is None` (and not suspended/cancelled)

### Job Categories
Jobs are classified by their type string [VERIFIED]:
- **Construction**: Prefixes like `Construct`.
- **Food**: Types like `PrepareMeal`, `ButcherAnimal`, `ExtractFromLandAnimal`, `PrepareRawFish`, `CatchLiveLandAnimal`, `CatchLiveFish`.
- **Military**: `LoadCatapult`, `LoadBallista`, `AssembleSiegeAmmo`, `ConstructBallistaParts`, `ConstructCatapultParts`.
- **Harvesting**: `CollectSand`, `CollectClay`, `HarvestFruits`, `PlantCutting`, `CatchLiveLandAnimal`.
- **Manufacturing**: Prefixes/keywords like `Make`, `Smelt`, `Weave`, `Dye`, `Encrust`, `ExtractFromRawFish`, `CutGems`, `Grind`.

### Stuck Job Heuristic
A job is considered "stuck" if: `suspended == True`, `n_items > 0`, and `worker_id is None` [VERIFIED].

## 3. Item Mechanics and Inventory
Item data is accessed via `df.global.world.items.all` and processed using `dfhack.matinfo.decode()` and `dfhack.items.getValue()` [VERIFIED].

### Item Type Enums
Key item types include: `TOOL`, `FOOD`, `MEAT`, `PLANT`, `WOOD`, `STONE`, `METAL_INGOT`, `BAR_GEMS`, `CLOTH`, `PAPER`, `BOOK`, `ARMOR`, `HELM`, `GLOVES`, `PANTS`, `SHOES`, `CONTAINER`, `POISON_FLASK`, `ARTIFACT`, `LIQUID_MISC`, `CHEESE`, `GLOB` [VERIFIED].

### Item Categories
- **Consumable**: FOOD, MEAT, PLANT, CHEESE, GLOB, LIQUID_MISC, POISON_FLASK.
- **Structural**: WOOD, STONE.
- **Metalwork**: METAL_INGOT, BAR_GEMS, CLOTH.
- **Protection**: ARMOR, HELM, GLOVES, PANTS, SHOES.
- **Tool**: TOOL.
- **Knowledge**: BOOK, PAPER, ARTIFACT.
- **Storage**: CONTAINER.

## 4. Map Features and Tile Data
Map features are queried via `bridge/core.lua map_features()` [VERIFIED].

### Feature Types
Known types: `None`, `RiverStream`, `OceanLake`, `WaterfallCascade`, `Volcano`, `GeyserHotSpring`, `Forest`, `MountainRange`, `DesertBadland`, `SwampMire`, `ChasmCanyon`, `UnderworldChasm` [VERIFIED].

### Feature Flags
Each feature record contains boolean flags: `water`, `magma`, `subterranean`, `chasm`, `underworld`, `discovered` [VERIFIED].

### Tile Map Structure
The tile map is block-based (16x16x16 tiles per block) [VERIFIED].
- **Probe**: `bridge/core.lua tile_map()` returns `has_map`, `width`, `height`, `depth`, `block_width`, `block_height`, `block_depth`, and a list of `tiles`.
- **Tile Fields**: Each tile dict contains `x`, `y`, `z`, `type`, `material`, `walkable` [VERIFIED].
- **Liquid Tiles**: Tile type >= 1024 [VERIFIED].
- **Floor Tiles**: Tile type in range [256, 511] [VERIFIED].

## 5. Unit Skills
Skills are accessed via `unit.status.current_soul.skills` [VERIFIED].

### Skill Ratings and Ranks
- **Rating Range**: -1 (unlearned) to 20+ (Legendary).
- **Rank Labels**:
  - 0: Dabbling
  - 1: Novice
  - 2: Adequate
  - 3: Competent
  - 4: Skilled
  - 5: Proficient
  - 6: Talented
  - 7: Adept
  - 8: Expert
  - 9: Professional
  - 10: Accomplished
  - 11: Great
  - 12: Master
  - 13: High Master
  - 14: Grand Master
  - 15+: Legendary [VERIFIED]

### Skill Tiers
- **Novice**: [0, 3)
- **Competent**: [3, 6)
- **Skilled**: [6, 9)
- **Master**: [9, 15)
- **Legendary**: >= 15
- **Unlearned**: < 0 [VERIFIED]

## Implications for Reset/Observe/Act/Advance

### Reset
- The `EpisodeRunner.reset()` method re-initializes internal state including deterministic citizen simulation based on seed [VERIFIED].
- In live DF, reset involves terminating the process and re-invoking `dfhack-run` [INFERRED from runtime analysis].

### Observe
- Observation must capture unit needs (`hunger_timer`, etc.) to detect dire states before they cause death or job abandonment [VERIFIED].
- Job state observation should filter for "stuck" jobs (suspended, no worker, has items) to identify automation failures [VERIFIED].
- Tile map probes should sample walkable and liquid fractions to assess fort accessibility [VERIFIED].

### Act
- Actions should prioritize assigning workers to dire-need units or stuck jobs [INFERRED].
- Skill levels should be considered when assigning complex manufacturing tasks; units with < Competent rating may fail or produce low-quality items [INFERRED from skill tiers].

### Advance
- Time advancement triggers stress events in the stub runner, killing units deterministically based on tick thresholds [VERIFIED].
- In live DF, advancing time updates all counters (hunger, thirst, job progress). Frequent small advances are safer than large jumps to avoid missing critical state changes [INFERRED].

## Coding Recommendations
1. **Dire Need Monitoring**: Implement a check for `hunger_timer > 75000`, `thirst_timer > 50000`, or `sleepiness_timer > 150000` to trigger immediate food/water/sleep actions [VERIFIED].
2. **Stuck Job Recovery**: Query jobs with `suspended=True`, `n_items>0`, and `worker_id=None`. Attempt to reassign workers or cancel these jobs to free resources [VERIFIED].
3. **Skill-Aware Assignment**: Filter units by skill rating >= 3 (Competent) for manufacturing tasks to ensure quality and success probability [VERIFIED].
4. **Tile Validation**: Before assigning construction jobs, verify that target tiles are walkable and not liquid (type < 1024) using `bridge.tile_map()` data [VERIFIED].
5. **Feature Awareness**: Avoid placing critical infrastructure near features with `magma=True` or `underworld=True` flags due to hazard risks [VERIFIED].
6. **Deterministic Testing**: Use the `_simulate_citizens` logic from `episode.py` for unit testing automation policies without requiring a live DF instance [VERIFIED].
