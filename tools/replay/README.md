# Replay viewer

Renders a Bonsai episode recording (`*.rec.jsonl.gz`) as the fort it actually was:
real Dwarf Fortress sprites, fog of war, material colours, liquids, a timeline, metric
curves, and the agent's decision feed with the intents the anti-forgery gate refused.

The 53.16 capture is self-contained. Besides tile ids it records the exact palette row
for each tile (full `prle` at a keyframe, compact `pset` afterwards), liquid depth/type,
raw creature ids, and building/item subtype, stage and material. A replay therefore
cannot accidentally be coloured with geology from another save.

When Premium graphics has rendered a map viewport, the capture also stores its exact
`background`/`background_two`/`top_shadow` texpos selections and packed floor, ramp and
shadow flags. Runtime texpos ids are resolved to stable raw `TILE_PAGE:column:row`
references, so a replay can use the engine-selected terrain token after textures are
reloaded or the atlas is rebuilt. These fields cover the visible viewport; cells that
were offscreen and older recordings retain the semantic tiletype fallback.

## Why you have to build it

The viewer draws with **Dwarf Fortress's own sprites**, taken from your DF install.
Those assets are proprietary (Bay 12 Games / Kitfox), so they are not in this repo —
`atlas.png`, `sprites.json`, `tilemap.json` and the built `viewer.html` are
gitignored. You own DF; you build the viewer from your own copy.

Nothing about the look is invented. DF v50 declares its whole game-state → sprite
mapping in plain-text raws:

```
[TILE_PAGE:WALL_SOIL] [FILE:images/wall_soil.png] [TILE_DIM:32:32]
[TILE_GRAPHICS:WALL_SOIL:2:4:SOIL_WALL_N_S_1]
```

Wall connectivity is encoded in the token *name* (`SOIL_WALL_N_S`, `STONE_WALL_NE`),
which is why an external renderer can reproduce DF's wall joining exactly, without
touching the binary.

## Build

From a machine with the DF install (paths are from the Bonsai lab host):

```sh
# 1. enum tables, from a LIVE DFHack (ids are renumbered between DF versions)
dfhack-run bonsai-dump-enums                  # writes /tmp/bonsai_enums.json
python compact_enums.py /tmp/bonsai_enums.json enums_compact.json

# 2. sprite atlas, from the graphics raws + images
python extract_sprites.py \
    /srv/df-bonsai/current/data/vanilla \
    /srv/df-bonsai/current/data/vanilla \
    ./build

# 3. tiletype -> sprite family mapping (validated against the atlas)
python build_tilemap.py enums_compact.json build/sprites.json build/tilemap.json

# 4. palette-swap table from the game's own palette image
python build_palette.py build \
    /srv/df-bonsai/current/data/vanilla/vanilla_descriptors_graphics/graphics/images/palettes.png

# 5. inline everything into one file
python build_viewer.py build
```

The image lookup is recursive. Point it at the real unflattened `data/vanilla` tree;
flattening hundreds of `graphics/images` directories can overwrite same-named sheets.
The audited 53.16 build loads 212 sheets with no missing pages, packs 7,481 non-empty
sprites, and maps 656 of 697 tiletypes (the four unmapped combinations are brook tops,
which intentionally reveal the level below).

`sprites.json` includes both `token -> source page/cell` and the reverse mapping. This
is capture metadata, not a second sprite-selection heuristic: DF's unstable texpos is
resolved through its live texture handler and then matched to the same vanilla raw cell.

`viewer.html` is then self-contained: open it and drop a recording on it. No server,
no network. (The atlas is inlined as a data URI rather than shipped alongside because
a canvas that draws a `file://` image is tainted, and tinting sprites by material
colour needs to read pixels back.)

Without an atlas the viewer still works — it falls back to glyph rendering, glyph from
tile shape and colour from tile material, which is DF's own decomposition.

## Use

- `viewer.html` — drop a recording, or `viewer.html?rec=<url>` when served over http
- `compare.html?a=<rec>&b=<rec>&al=<label>&bl=<label>` — two runs on one timeline
- `python render_frame.py <recording-or-raw-capture> <z> <out.png> [frame] [build]`
  — independent PNG renderer; set `BONSAI_CROP=x1,y1,x2,y2` for a world-coordinate crop

Both renderers also accept raw `bonsai-map-capture` JSONL (`kind=kf|d`) directly. The
browser chooses the z-level with the most fort activity instead of opening a large save
on an arbitrary empty midpoint. A DF/enums version mismatch is shown prominently in the
browser and rejected by the static renderer.

For a targeted fidelity capture of a very mature fort, pass an optional exact box as
`x,y,z,width,height,depth`. Normal episode capture omits it and still records the whole
fort; the exact box avoids waiting for all 65+ occupied z-levels just to audit one room:

```sh
dfhack-run bonsai-map-capture kf /tmp/room.jsonl 96,60,162,96,72,5
```

Furniture, wagons, workshops and furnaces use the game's real tokens, including the
extra north overhang row, multi-tile build stages, and base/overlay passes. Terrain uses
DF's sparse five-frame hidden-rock detail, opaque wall backing plus wall-shadow layer, and distinct base/overlay/multilevel
ramp plus ramp-shadow layers. On-ground items use item family and material; inventory and building
components are excluded. Creatures use their raw id when DF ships graphics for that
creature. Raws without a graphical token retain a small fallback marker rather than
borrowing an incorrect species. Dwarf equipment/tissue layering and the surrounding
Steam UI are not reconstructed; the fort viewport is the fidelity target.

The comparison refuses to render two runs from different `regime_key`s (different
save, engine build, horizon or metric weighting puts them on different scales), and
asks for each model's K-run scores before it will name a winner — one episode of a
non-reproducible game is an anecdote, not a measurement.

## Rebuild after a DF upgrade

Tiletype, profession, job, workshop and furnace ids are renumbered between DF versions.
Re-run the whole pipeline; `build_tilemap.py` reports coverage, so a renamed sprite
family shows up as a coverage drop rather than as silently missing terrain.
`regime_key` already pins `df_version`, so recordings from different builds are never
compared, and the viewer independently checks the capture version against its assets.
