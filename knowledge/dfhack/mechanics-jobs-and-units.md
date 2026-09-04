# Job Categorization and Unit Needs Heuristics

This note details the specific heuristics, enum mappings, and state transition logic used in the DF-Bonsai bridge (`bridge/probe.py`) to interpret Dwarf Fortress 53.15 game state via DFHack 53.15-r2.

## Job State and Categorization

The job system is interpreted through specific boolean flags and string prefixes found in `bridge/probe.py` (lines 396-408, 411-418).

### State Derivation [VERIFIED]
Job states are derived from the following fields in the job record:
- **Cancelled**: `job_record.get("cancelled")` is True.
- **Suspended**: `job_record.get("suspended")` is True.
- **Active**: `job_record.get("worker_id")` is not None (and not cancelled/suspended).
- **Queued**: Default state if none of the above apply [VERIFIED].

### Category Classification [VERIFIED]
Jobs are categorized based on string containment in the job type name (`jt`):
- **Construction**: Contains `"Construct"`.
- **Food**: Contains any of `"PrepareMeal"`, `"ButcherAnimal"`, `"ExtractFromLandAnimal"`, `"PrepareRawFish"`, `"CatchLiveLandAnimal"`, `"CatchLiveFish"`.
- **Military**: Contains `"LoadCatapult"`, `"LoadBallista"`, `"AssembleSiegeAmmo"`, `"ConstructBallistaParts"`, or `"ConstructCatapultParts"`.
- **Harvesting**: Contains `"CollectSand"`, `"CollectClay"`, `"HarvestFruits"`, `"PlantCutting"`, or `"CatchLiveLandAnimal"`.
- **Manufacturing**: Contains `"Make"`, `"Smelt"`, `"Weave"`, `"Dye"`, `"Encrust"`, or `"ExtractFromRawFish"`.
- **Other**: Fallback category [VERIFIED].

### Suspicious Jobs Heuristic [INFERRED]
A job is considered "stuck" or suspicious if:
1. `suspended` is True.
2. `n_items` > 0.
3. `worker_id` is None.
This indicates a job with materials but no assigned worker, potentially lost due to state desynchronization [INFERRED].

## Building Observation

Building records are filtered and classified using fields defined in `BUILDING_SCHEMA_KEYS` (lines 461-464).

### Completion Status [VERIFIED]
A building is considered complete if:
- `built` is True.
- `build_stage` >= 0.

### Type Labeling [VERIFIED]
The human-readable type label is extracted by splitting the `type` string on "." and taking the last element (e.g., `df.building_type.Workshop` -> `Workshop`). Known types include `Workshop`, `Furnace`, `Storage`, etc. [VERIFIED].

## Item Inventory Mechanics

Item records are classified using `ITEM_TYPE_ENUM_MAP` (lines 508-531) and categorized into resource groups.

### Resource Categories [VERIFIED]
- **Consumable**: `FOOD`, `MEAT`, `PLANT`, `CHEESE`, `GLOB`, `LIQUID_MISC`, `POISON_FLASK`.
- **Structural**: `WOOD`, `STONE`.
- **Metalwork**: `METAL_INGOT`, `BAR_GEMS`, `CLOTH`.
- **Protection**: `ARMOR`, `HELM`, `GLOVES`, `PANTS`, `SHOES`.
- **Tool**: `TOOL`.
- **Knowledge**: `BOOK`, `PAPER`, `ARTIFACT`.
- **Storage**: `CONTAINER`.
- **Other**: Fallback [VERIFIED].

### Value Calculation [VERIFIED]
Total inventory value is the sum of the `value` field (in bits) for all items. High-value items are those exceeding a threshold (default 1000 bits) [VERIFIED].

## Unit Population and Position

Unit records contain `pos` as `[x, y, z]` or dict `{x, y, z}` and `civ_id` for civilization grouping.

### Population Counts [VERIFIED]
- **Alive**: `killed` is False.
- **Dead**: `killed` is True.
- **Total**: Length of unit list [VERIFIED].

### Position Filtering [VERIFIED]
Units can be filtered by Z-level using `pos[2]` or `pos.get("z")`. Nearby units are calculated using Manhattan distance on X-Y coordinates only, ignoring Z-level differences [VERIFIED].

## Unit Needs and Dire Need Thresholds

Unit needs are tracked via counters in `COUNTERS_1_FIELDS` and `COUNTERS_2_FIELDS` (lines 598-607).

### Dire Need Thresholds [VERIFIED]
A unit is in "dire need" if any of the following thresholds are exceeded:
- **Hunger**: `hunger_timer` > 75,000.
- **Thirst**: `thirst_timer` > 50,000.
- **Sleepiness**: `sleepiness_timer` > 150,000.

### Severity Scoring [INFERRED]
A severity score (0-6) is calculated by:
- Adding 1 point for each dire need threshold exceeded.
- Adding 0.5 points for each non-zero physical distress flag (`pain`, `nausea`, `dizziness`, `suffocation`) [INFERRED].

## Implications for Reset/Observe/Act/Advance

1. **Reset**: The `EpisodeRunner.reset()` method re-initializes unit states and job queues. Job state derivation must be re-evaluated after reset as worker assignments may change [VERIFIED].
2. **Observe**: Observations must parse job records to determine active vs. queued work. Suspicious jobs (stuck) should be flagged for potential intervention [INFERRED].
3. **Act**: Actions affecting jobs (e.g., suspending/resuming) will change the `suspended` and `worker_id` fields, altering state classification [VERIFIED].
4. **Advance**: Time advancement triggers need counter increments. Monitoring dire need thresholds is critical for unit survival heuristics [VERIFIED].

## Coding Recommendations

1. **Job State Handling**: Always check `cancelled` before `suspended` to avoid misclassifying cancelled jobs as suspended.
2. **Stuck Job Detection**: Implement the "suspicious jobs" heuristic to detect and potentially cancel or reassign stuck jobs during observation loops.
3. **Need Monitoring**: Poll unit needs regularly and trigger emergency actions (e.g., food/water delivery) when dire need thresholds are approached.
4. **Building Completion**: Use `is_complete_building` logic to filter out unfinished structures from resource availability calculations.
5. **Position Consistency**: Ensure position data is normalized to `[x, y, z]` tuples before distance calculations to handle both list and dict formats [VERIFIED].

## Uncertainties

- The exact impact of `build_stage` values on building functionality is not fully detailed; only completion status is verified [OPEN].
- The specific behavior of "stuck" jobs in live DF instances (whether they auto-resolve) is inferred from heuristic design, not observed resolution [OPEN].
