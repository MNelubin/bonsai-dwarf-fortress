# DF 53.16 tile-transition research

Research date: 2026-08-23. This document records evidence before any further
transition-rendering changes. It deliberately separates facts observed in the
53.16 game data and DFHack from hypotheses about how to reproduce the result.

## Conclusion

There is no single Dwarf Fortress "tile transition" algorithm. The premium
renderer exposes independent decisions for floor edging, ramp topology, wall
and ramp shadows, multilevel/open-air display, and later object layers. The
current replay viewer reconstructs several of these decisions from neighboring
tiletype families. That loses information and already produces provably wrong
choices.

The robust design is to record the decisions already made by DF's renderer and
replay them, instead of trying to duplicate its hidden priority rules from a
map tiletype alone.

## Primary evidence

- Installed 53.16 vanilla definitions:
  `data/vanilla/vanilla_environment/graphics/graphics_tiles.txt` and
  `tile_page_environment.txt` in the 53.16 Steam release on the lab host.
- The local extracted atlas, `tools/replay/build/atlas.png`, and its token index,
  `tools/replay/build/sprites.json`, were built from those game resources.
- DFHack's official [`devel/inspect-screen`](https://docs.dfhack.org/en/50.13-r4/docs/tools/devel/inspect-screen.html)
  documentation states that it exposes every texture and texture flag associated
  with a map tile. Its
  [official source](https://raw.githubusercontent.com/DFHack/scripts/master/devel/inspect-screen.lua)
  names and decodes the relevant `gps.main_viewport` fields.
- DFHack's official [`devel/export-map`](https://docs.dfhack.org/en/latest/docs/tools/devel/export-map.html)
  documentation independently distinguishes shape, material, special, variant,
  visibility and liquids. These are inputs, not one graphical identity.
- DFHack's official [`gui/tiletypes`](https://docs.dfhack.org/en/53.07-r1/docs/tools/gui/tiletypes.html)
  documentation confirms that a functional/displayable ramp also requires the
  corresponding `RAMP_TOP` on the level above.
- DFHack's official [`reveal`](https://docs.dfhack.org/en/stable/docs/tools/reveal.html)
  documentation notes that, in graphics mode, solid tiles not adjacent to open
  space are not rendered. Visibility and exposure therefore affect rendering,
  not just fog color.

## What DF actually keeps separate

`devel/inspect-screen.lua` exposes the following independent viewport state:

| Concern | DF viewport data | Meaning for replay |
| --- | --- | --- |
| base terrain | `screentexpos_background` | first selected terrain texture |
| floor transition | `screentexpos_floor_flag` | four 8-bit edge choices: S, W, E, N, plus special texture |
| second terrain pass | `screentexpos_background_two` | another game-selected terrain texture, not derivable from one token |
| ramps | `screentexpos_ramp_flag` | type, 8 wall-neighbor bits, dark corners, open-air sides, arrows, color row |
| wall/ramp shadows | `screentexpos_shadow_flag` | wall adjacency plus 16 distinct ramp-on-floor shadow flags |
| upper shadow | `screentexpos_top_shadow` | a later shadow pass |
| objects | building/item/vehicle/vermin/creature fields | layers selected after terrain state |

The source ordering is useful evidence about the available passes, but it is not
by itself proof of every alpha-composition detail. Exact composition order must
be validated from captured viewport output.

## Confirmed defects in the current viewer

### 1. Floor edge sprites are spatially inverted

The 53.16 `FLOORS` page defines `_1.._9` as a 3x3 set. Alpha bounding boxes in
the extracted 32x32 `STONE_FLOOR` sprites are:

| token | nontransparent location | alpha pixels |
| --- | --- | ---: |
| `_1` | bottom-right | 20 |
| `_2` | bottom edge | 83 |
| `_3` | bottom-left | 19 |
| `_4` | right edge | 61 |
| `_5` | full cell | 1024 |
| `_6` | left edge | 71 |
| `_7` | top-right | 22 |
| `_8` | top edge | 100 |
| `_9` | top-left | 12 |

`render_frame.py:348-376` and the mirrored browser implementation currently
interpret `_2` as north, `_4` as west, `_6` as east, and `_8` as south. The
pixels prove the opposite screen edges. The four corners are inverted in the
same way.

### 2. Floor edging uses the wrong source of truth

The current algorithm draws the full `_5` tile and then overlays a feather from
the **same family** whenever a neighbor's family differs. That cannot reproduce
a transition selected between two materials. It also:

- ignores different material/palette rows when both tiles map to `STONE_FLOOR`;
- treats every different sprite family as the same kind of boundary;
- maps grass tiletypes to `PLANT_GRASS` variants, so it cannot express the raw
  `GRASS_1..9` terrain edge family;
- has no representation for DF's four independent 8-bit edging values or
  `screentexpos_background_two`.

Therefore simply correcting the `_1.._9` directions is necessary but not
sufficient.

### 3. The all-cardinal ramp token falls back to `OTHER`

Exhaustively enumerating all 256 eight-neighbor masks through the current
`ramp_connection_suffix()` produces all 47 canonical ramp configurations. For
the all-cardinal case it produces `N_S_W_E`, while the 53.16 raws use
`N_S_E_W`. As a result all three synchronized families miss the token and fall
back to `OTHER`:

- material ramp (`*_RAMP_WITH_WALL_*`);
- `OVERLAY_RAMP_WITH_WALL_*`;
- `MULTILEVEL_RAMP_WITH_WALL_*`.

The other 46 generated configurations exist in the extracted atlas. This is a
small concrete bug, but it also demonstrates why token-name reconstruction
needs exhaustive fixtures.

### 4. Wall shadows are reduced to four straight pieces

The vanilla `SHADOWS_WALL` page contains 15 meaningful tokens: four straight
edges, four `AT_CORNER` pieces and eight `NEAR_*_OPEN_*` entries (with shared
sheet positions). The viewer only draws `WALL_SHADOW_STRAIGHT_{N,S,W,E}`.
Corners and open-corner termination are therefore necessarily wrong even when
the wall sprite itself is correct.

### 5. Ramp shadows are mostly absent

The vanilla `SHADOWS_RAMP` page contains:

- 16 named `RAMP_SHADOW_ON_FLOOR_*` configurations;
- four `RAMP_SHADOW_ON_RAMP_{N,S,W,E}` pieces;
- four inside-corner pieces;
- sixteen light/heavy triangular corner pieces.

The viewer draws only the four straight on-ramp pieces. It cannot reproduce the
shadow continuing from a ramp onto a neighboring floor, inside corners, or the
light/heavy corner choice. DF's viewport exposes all 16 floor-shadow decisions
explicitly in `screentexpos_shadow_flag`.

### 6. Open-air/multilevel transitions are approximate

The 53.16 raw has a dedicated `MULTILEVEL_AIR` texture in addition to the full
47-token `MULTILEVEL_RAMP` family. The viewer instead searches downward for a
lower tile and dims it. That can approximate depth, but it does not reproduce
the game-selected air overlay, open-air side bits, or top-shadow pass.

## What remains unproven

- The priority rules that choose which material contributes each floor edge.
- Exact alpha order when `background_two`, multilevel, shadows, liquids,
  buildings, items, and units coexist.
- When ramp corner triangles are light versus heavy.
- Which transitions vary with hidden/light/outside state rather than tiletype.

Those should not be guessed from screenshots. DF already exposes the selected
flags and texture ids.

## Runtime probe result

A read-only probe initially appeared to fail because the 53.16 `dfhack-run` client
segfaults after the command. Subsequent checks proved that the in-process Lua script
had completed first and written valid JSON. A live 22x16 viewport yielded all 352
background and floor-flag cells plus stable page/cell references for 24 used texpos
ids. The initial surface viewport had no ramps or shadows, so those arrays were
correctly all zero there. Moving the viewport in this headless runtime changes the
coordinates but does not make Premium redraw its layer buffers; specialized ramp and
shadow capture still requires an initially loaded view or a render-context callback.

The live data also disproved one early interpretation: `s_edging`/`w_edging`/
`e_edging`/`n_edging` values such as 0, 1, 2 and 8 are selectors/priorities, not palette
rows. They are preserved verbatim but are not recolored as materials.

The existing `tools/replay/bonsai-screengrab.lua` only reads the final flattened
screen tile. That is useful for pixel equivalence, but it omits the transition
flags needed to explain and replay each layer.

## Recommended implementation sequence

1. Add a capture path that runs in DFHack's core/render context and records, per
   visible map cell, `background`, `background_two`, floor, ramp, shadow and
   `top_shadow` state alongside the current semantic map capture.
2. Decode the flags exactly as `devel/inspect-screen.lua` does. Preserve the raw
   packed values too, so new DF versions can be re-decoded without recapturing.
3. Make both Python and browser viewers consume captured renderer decisions.
   Keep neighbor inference only as an explicitly marked fallback for old logs.
4. Generate exhaustive transition fixtures: 16 cardinal floor/wall cases, all
   256 ramp neighborhoods (47 canonical outputs), wall-shadow corners, all 16
   ramp-on-floor shadows, and vertical ramp/open-air cases.
5. Produce per-layer contact sheets and final composites, then compare against
   both the mature 53.16 fort and a fresh embark. Acceptance is visual and
   pixel/texture-id based, not merely a green unit test.

This avoids another cycle of tuning a plausible-looking global screenshot while
individual tile boundaries remain structurally wrong.
