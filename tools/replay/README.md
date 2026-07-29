# Replay viewer

Renders a Bonsai episode recording (`*.rec.jsonl.gz`) as the fort it actually was:
real Dwarf Fortress sprites, a timeline, metric curves, and the agent's decision feed
with the intents the anti-forgery gate refused.

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
    <dir with every graphics/images/*.png> \
    ./build

# 3. tiletype -> sprite family mapping (validated against the atlas)
python build_tilemap.py enums_compact.json build/sprites.json build/tilemap.json

# 4. inline everything into one file
python build_viewer.py build
```

`viewer.html` is then self-contained: open it and drop a recording on it. No server,
no network. (The atlas is inlined as a data URI rather than shipped alongside because
a canvas that draws a `file://` image is tainted, and tinting sprites by material
colour needs to read pixels back.)

Without an atlas the viewer still works — it falls back to glyph rendering, glyph from
tile shape and colour from tile material, which is DF's own decomposition.

## Use

- `viewer.html` — drop a recording, or `viewer.html?rec=<url>` when served over http
- `compare.html?a=<rec>&b=<rec>&al=<label>&bl=<label>` — two runs on one timeline

The comparison refuses to render two runs from different `regime_key`s (different
save, engine build, horizon or metric weighting puts them on different scales), and
asks for each model's K-run scores before it will name a winner — one episode of a
non-reproducible game is an anecdote, not a measurement.

## Rebuild after a DF upgrade

Tiletype, profession and job ids are renumbered between DF versions. Re-run the whole
pipeline; `build_tilemap.py` reports coverage, so a renamed sprite family shows up as
a coverage drop rather than as silently missing terrain. `regime_key` already pins
`df_version`, so recordings from different builds are never compared.
