from pathlib import Path
import sys


REPLAY = Path(__file__).resolve().parents[2] / "tools" / "replay"
sys.path.insert(0, str(REPLAY))

from entity_sprites import (building_cells, creature_token, item_token,  # noqa: E402
                            liquid_token)
from extract_sprites import index_images, load_sheet  # noqa: E402
from render_frame import (decode_floor_flag, exposed_wall_suffix,  # noqa: E402
                          grass_edge_fragments, hidden_detail_variant, load_frames,
                          ramp_connection_suffix, ramp_suffix_from_flag,
                          tile_wall_suffix)


def test_capture_is_versioned_and_records_visual_state():
    lua = (Path(__file__).resolve().parents[1] / "bonsai_lab_agent" / "dfhack"
           / "bonsai-map-capture.lua").read_text(encoding="utf-8")
    assert '"lrle"' in lua and "flow_size" in lua and "liquid_type" in lua
    assert '"prle"' in lua and "CONSTRUCTION_ROW" in lua and "block_geo" in lua
    assert '"pset"' in lua and "G.BONSAI_MAP_PAL" in lua
    assert "x,y,z,width,height,depth" in lua and "if not exact then" in lua
    assert '"dfv"' in lua and "dfhack.getDFVersion()" in lua
    assert '"viewport"' in lua and "screentexpos_floor_flag" in lua
    assert "screentexpos_ramp_flag" in lua and "screentexpos_shadow_flag" in lua
    assert "sx * vh + sy" in lua  # DF viewport arrays are x-major
    assert "df.global.texture.page" in lua and '"tex":%s' in lua
    assert "raw.creature_id" in lua and "raw.caste" in lua
    assert "b:getSubtype()" in lua and "b.build_stage" in lua
    assert "it:getQuality()" in lua and "it.flags.in_inventory" in lua
    assert "it.flags.on_ground" in lua
    assert "material_class(mt, mi)" in lua and "material_row(mt, mi)" in lua
    static = (REPLAY / "render_frame.py").read_text(encoding="utf-8")
    browser = (REPLAY / "viewer.template.html").read_text(encoding="utf-8")
    assert '("map", "kf", "d")' in static
    assert 'array("H", grid)' in static and "bytearray(len(grid))" in static
    assert "BONSAI_CROP" in static
    assert 'e.kind === "kf"' in browser
    assert "const zScore = new Map()" in browser


def test_furniture_and_item_use_real_material_family():
    enums = {"bld": {1: "Bed"}, "item": {20: "TABLE"}}
    tokens = {"ITEM_BED_WOOD", "ITEM_BED_STONE", "ITEM_TABLE_STONE"}
    # building schema: id,type,x1,y1,x2,y2,z,sub,custom,stage,max,mt,mi,class,row
    bed = [7, 1, 10, 11, 10, 11, 5, -1, -1, 1, 1, 0, 0, 1, 13]
    assert building_cells(bed, enums, tokens) == [(10, 11, "ITEM_BED_WOOD")]
    # item schema ends in class,row
    table = [8, 20, 12, 13, 5, -1, 0, 0, 0, 1, 2, 51]
    assert item_token(table, enums, tokens) == "ITEM_TABLE_STONE"
    wood = [9, 5, 1, 2, 3, -1, 0, 0, 0, 1, 1, 13]
    assert item_token(wood, {"item": {5: "WOOD"}}, {"ITEM_WOOD"}) == "ITEM_WOOD"


def test_workshop_reconstructs_one_live_texture_without_raw_row_zero():
    enums = {"bld": {13: "Workshop"}, "workshop": {0: "Carpenters"}}
    tokens = {
        *(f"WORKSHOP_CARPENTER_S2_{x}_{y}" for x in range(3) for y in range(1, 4)),
        *(f"WORKSHOP_CARPENTER_OVERLAY_S2_{x}_{y}" for x in range(3) for y in range(1, 4)),
        "WORKSHOP_CARPENTER_S2_0_0",
        "WORKSHOP_CARPENTER_OVERLAY_S2_0_0",
        "WORKSHOP_CARPENTER_OVERLAY_S2_2_3",
    }
    workshop = [1, 13, 20, 30, 22, 32, 9, 0, -1, 2, 3, 0, 0, 1, 13]
    cells = building_cells(workshop, enums, tokens)
    assert len(cells) == 18
    assert (20, 30, "WORKSHOP_CARPENTER_S2_0_1") in cells
    assert (22, 32, "WORKSHOP_CARPENTER_S2_2_3") in cells
    assert (20, 30, "WORKSHOP_CARPENTER_OVERLAY_S2_0_1") in cells
    assert all(y >= 30 for _, y, _ in cells)
    assert not any(token.endswith("_0_0") for _, _, token in cells)


def test_wall_uses_direction_encoded_by_tiletype_not_neighbour_guess():
    assert tile_wall_suffix(["WALL", "CONSTRUCTION", "constructed wall RUD", -1]) == "W"
    assert tile_wall_suffix(["WALL", "MINERAL", "smooth vein wall LR", -1]) == "N_S"
    assert tile_wall_suffix(["WALL", "CONSTRUCTION", "constructed wall RD", -1]) == "N_W"
    assert tile_wall_suffix(["WALL", "CONSTRUCTION", "constructed wall LRUD", -1]) == ""
    assert tile_wall_suffix(["WALL", "STONE", "stone wall", -1]) is None


def test_natural_wall_fallback_names_exposed_not_connected_edges():
    connected = {(0, -1), (0, 1)}
    solid = lambda x, y: (x, y) in connected
    assert exposed_wall_suffix(solid, 0, 0) == "W_E"
    assert exposed_wall_suffix(lambda _x, _y: True, 0, 0) == ""
    assert exposed_wall_suffix(lambda _x, _y: False, 0, 0) == "N_S_W_E"


def test_creature_and_liquid_tokens_are_not_generic_markers():
    tokens = {"CREATURE_HORSE", "CREATURE_DWARF", "WATER", "MAGMA_1", "MAGMA_3"}
    horse = [2, 1, 1, 4, 0, -1, 0, 0, 10, "HORSE", "MALE"]
    assert creature_token(horse, tokens) == "CREATURE_HORSE"
    assert liquid_token(7, tokens) == "WATER"
    assert liquid_token(8 | 2, tokens) == "MAGMA_1"
    assert liquid_token(8 | 7, tokens) == "MAGMA_3"


def test_ramp_connectivity_uses_cardinals_and_only_exposed_corners():
    # North and east suppress their shared NE corner; the opposite SW corner remains
    # meaningful because neither of its adjacent cardinal walls exists.
    walls = {(0, -1), (1, 0), (-1, 1)}
    assert ramp_connection_suffix(lambda x, y: (x, y) in walls, 0, 0) == "N_E_SW"


def test_transition_flags_decode_in_dfhack_published_order():
    flag = 11 | (22 << 8) | (33 << 16) | (44 << 24) | (5 << 32)
    assert decode_floor_flag(flag) == {"S": 11, "W": 22, "E": 33,
                                       "N": 44, "special": 5}
    # ramp low byte is type; wall bits are N,W,E,S,NW,NE,SW,SE
    ramp = 7 | (0b00001111 << 8)
    assert ramp_suffix_from_flag(ramp) == "N_S_E_W"


def test_grass_edges_are_foreign_fragments_not_stone_overlays():
    grass = {(0, -1), (-1, 0), (1, 1)}
    assert grass_edge_fragments(lambda dx, dy: (dx, dy) in grass) == [
        "GRASS_8", "GRASS_6", "GRASS_1"
    ]


def test_all_cardinal_ramp_uses_the_real_raw_token_order():
    assert ramp_connection_suffix(lambda _x, _y: True, 0, 0) == "N_S_E_W"


def test_all_256_ramp_neighbourhoods_reduce_to_47_raw_shapes():
    points = [(0, -1), (0, 1), (-1, 0), (1, 0),
              (-1, -1), (1, -1), (-1, 1), (1, 1)]
    suffixes = set()
    for mask in range(256):
        walls = {point for bit, point in enumerate(points) if mask & (1 << bit)}
        suffixes.add(ramp_connection_suffix(lambda x, y: (x, y) in walls, 0, 0))
    assert len(suffixes) == 47
    assert "N_S_E_W" in suffixes
    assert "N_S_W_E" not in suffixes


def test_hidden_rock_detail_is_sparse_deterministic_and_uses_all_frames():
    a = [hidden_detail_variant(x, y, 164) for y in range(128) for x in range(128)]
    b = [hidden_detail_variant(x, y, 164) for y in range(128) for x in range(128)]
    assert a == b
    assert 0.02 < sum(bool(v) for v in a) / len(a) < 0.05
    assert set(a) == {0, 1, 2, 3, 4, 5}


def test_sheet_lookup_accepts_unflattened_real_df_tree(tmp_path):
    from PIL import Image

    nested = tmp_path / "vanilla_items_graphics" / "graphics" / "images"
    nested.mkdir(parents=True)
    Image.new("RGBA", (32, 32), (1, 2, 3, 255)).save(nested / "item_bed.png")
    index = index_images(tmp_path)
    loaded = load_sheet(tmp_path, "images/item_bed.png", index)
    assert loaded is not None and loaded.size == (32, 32)


def test_raw_capture_palette_delta_reconstructs_without_episode_wrapper(tmp_path):
    import json

    path = tmp_path / "capture.jsonl"
    rows = [
        {"kind": "kf", "tick": 1, "origin": [0, 0, 0], "dims": [1, 1, 1],
         "rle": [10, 1], "hrle": [0, 1], "lrle": [0, 1], "prle": [50, 1]},
        {"kind": "d", "tick": 2, "set": [0, 11], "hrle": [0, 1],
         "lrle": [7, 1], "pset": [0, 51]},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    _, frames = load_frames(path)
    assert len(frames) == 2
    assert list(frames[1]["grid"]) == [11]
    assert list(frames[1]["palette"]) == [51]
    assert list(frames[1]["liquid"]) == [7]


def test_raw_capture_reconstructs_optional_viewport_transition_rles(tmp_path):
    import json

    path = tmp_path / "viewport.jsonl"
    row = {"kind": "kf", "tick": 1, "origin": [10, 20, 30], "dims": [2, 1, 1],
           "rle": [1, 2], "hrle": [0, 2], "lrle": [0, 2], "prle": [1, 2],
           "viewport": {"origin": [10, 20, 30], "dims": [2, 1],
                        "bgrle": [101, 2], "bg2rle": [0, 2],
                        "frle": [0, 1, 1234, 1], "rrle": [9, 2],
                        "srle": [7, 2], "trle": [202, 2],
                        "tex": [[101, "FLOORS", 1, 4]]}}
    path.write_text(json.dumps(row), encoding="utf-8")
    _, frames = load_frames(path)
    vp = frames[0]["viewport"]
    assert vp["bg"] == [101, 101]
    assert vp["floor"] == [0, 1234]
    assert vp["ramp"] == [9, 9]
    assert vp["shadow"] == [7, 7]
    assert vp["top"] == [202, 202]
    assert vp["texrefs"] == {101: "FLOORS:1:4"}
