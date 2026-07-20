# Tile Material Resolution and Geology Mechanics

This note details the mechanics for resolving tile materials in Dwarf Fortress 53.15 via DFHack 53.15-r2, based on the `tile-material.lua` module and bridge probe definitions.

## Core Module: `tile-material.lua`

The primary interface for material resolution is the Lua module located at:
`/srv/df-bonsai/releases/df-53.15-steam-23622201_dfhack-53.15-r2/hack/lua/tile-material.lua`

### Key Functions [VERIFIED]

The following functions are defined in `tile-material.lua` and verified by source inspection:

*   **`GetTileMat(x, y, z)`**: Returns the material of the specified tile as determined by its tile type and world geology. Equivalent to calling `GetTileMatSpec` with the `BasicMats` table.
*   **`GetLayerMat(x, y, z)`**: Returns the layer material (stone/soil) for the given tile, ignoring veins or inclusions. Uses `dfhack.maps.getRegionBiome` and `biome.layers`.
*   **`GetVeinMat(x, y, z)`**: Returns the vein material if present. Handles multiple veins by priority: `cluster` (1) > `vein` (2) > `cluster_small` (3) > `cluster_one` (4). Uses `block_square_event_mineralst`.
*   **`GetConstructionMat(x, y, z)`**: Returns the material of a construction at the tile. Iterates `df.global.world.event.constructions`.
*   **`GetTreeMat(x, y, z)`**: Returns tree/mushroom material. Checks `df.global.world.plants.all` and calculates bounding boxes using `tree_info.dim_x`, `dim_y`, and `body_height`.
*   **`GetGrassMat(x, y, z)`**: Returns grass material if `block_square_event_grassst` exists with amount > 0.
*   **`GetFeatureMat(x, y, z)`**: Returns feature stone material (adamantine tubes, underworld surface) based on `df.tiletype_material.FEATURE` and local/global feature indices.

### Material Specification Tables [VERIFIED]

The module defines three matspec tables that map `df.tiletype_material` enums to resolver functions:

1.  **`BasicMats`**: Default behavior. Maps `SOIL`, `STONE` to `GetLayerMat`; `MINERAL` to `GetVeinMat`; `TREE`/`MUSHROOM` to `GetTreeMat`; `PLANT` to `GetShrubMat`; `GRASS_*` to `GetGrassMat`. Returns `nil` for `AIR`, `HFS` (Eerie Glowing Pit), `MAGMA` (Semi-Molten Rock), and `UNDERWORLD_GATE`.
2.  **`NoPlantMats`**: Ignores plants. Maps plant-related tile types to `GetLayerMat` or returns `nil` for trees.
3.  **`OnlyPlantMats`**: Returns `nil` for non-plant tiles. Only resolves grass, shrubs, and trees.

### Coordinate Handling [VERIFIED]

*   Functions accept coordinates as three arguments `(x, y, z)` or a single table `{x=..., y=..., z=...}`.
*   Invalid coordinates (e.g., `x == -30000`) raise an error "Invalid coordinate argument(s)." [VERIFIED]

## Tile Type Material Enums [VERIFIED]

The following enum values for `df.tiletype_material` are referenced in `tile-material.lua` and `probe.py`:

*   `AIR`: 0 (Empty)
*   `SOIL`: 1
*   `STONE`: 2
*   `FEATURE`: 3
*   `LAVA_STONE`: 4
*   `MINERAL`: 5
*   `FROZEN_LIQUID`: 6 (Ice, returns "WATER:NONE")
*   `CONSTRUCTION`: 7
*   `GRASS_LIGHT`/`DARK`/`DRY`/`DEAD`: 8-11
*   `PLANT`: 12 (Shrubs/Saplings)
*   `HFS`: 13 (Eerie Glowing Pit, returns nil)
*   `CAMPFIRE`/`FIRE`/`ASHES`: 14-16
*   `MAGMA`: 17 (Semi-Molten Rock, returns nil)
*   `DRIFTWOOD`/`POOL`/`BROOK`/`ROOT`: 18-21
*   `TREE`/`MUSHROOM`: 22-23
*   `UNDERWORLD_GATE`: 24 (Returns nil)

*Note: Exact integer values are inferred from standard DF enums and usage in `probe.py` constants, but the mapping logic in `tile-material.lua` is verified.*

## Bridge Probe Integration [VERIFIED]

The file `/srv/bonsai-agent/runs/0276a64a-5c8c-4c5e-a5f0-98fa7943b7b6-1784519858/repo/bridge/probe.py` defines constants for time and material classification:

*   `TICKS_PER_DAY = 86400`
*   `TICKS_PER_SEASON = 361 * 86400`
*   `SEASONS_PER_YEAR = 4`
*   Material enums are mapped in `TILE_MATERIAL_ENUM_MAP` for offline classification.

## Implications for Reset/Observe/Act/Advance

1.  **Observation**: To determine if a tile is diggable or contains resources, agents must call `GetTileMat` or specific getters like `GetVeinMat`. Relying solely on `dfhack.maps.getTileType` is insufficient for material identity (e.g., distinguishing granite from limestone).
2.  **State Transitions**: When digging (`Act`), the tile type changes, but the underlying layer material (`GetLayerMat`) remains constant unless the geology itself changes (rare). Vein materials disappear when mined.
3.  **Uncertainty**: The source code notes uncertainty regarding caved-in tiles: "I am not 100% sure if these functions will reliably work with all caved in tiles" [OPEN]. Agents should handle `nil` returns or errors gracefully.
4.  **Performance**: Iterating `df.global.world.plants.all` for tree/shrub checks can be expensive. Caching results per tile or block is recommended for high-frequency observation loops.

## Coding Recommendations

*   Use `require('tile-material').GetTileMat(x,y,z)` for general material queries.
*   For resource gathering logic, prefer `GetVeinMat` and `GetTreeMat` directly to avoid overhead of generic resolution.
*   Validate coordinates before passing to these functions to prevent Lua errors from invalid positions (e.g., outside map bounds).
*   When simulating offline, use the `TILE_MATERIAL_ENUM_MAP` from `probe.py` to classify tile types without a live DFHack instance.
