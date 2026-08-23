"""Translate compact map-capture entities to tokens from DF's own graphics raws.

The capture arrays are append-only: old recordings stop after the original fields,
while 53.16 recordings add subtype, build stage and material information. Helpers here
therefore default every new field and never require a recording migration.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

MATERIAL = {1: "WOOD", 2: "STONE", 3: "METAL", 4: "GLASS"}

FURNITURE = {
    "Chair": "ITEM_CHAIR",
    "Bed": "ITEM_BED",
    "Table": "ITEM_TABLE",
    "Coffin": "ITEM_COFFIN",
    "Door": "ITEM_DOOR",
    "Box": "ITEM_BOX",
    "Weaponrack": "ITEM_WEAPON_RACK",
    "Armorstand": "ITEM_ARMOR_STAND",
    "Cabinet": "ITEM_CABINET",
    "Statue": "ITEM_STATUE",
    "Hatch": "ITEM_HATCH",
    "Slab": "ITEM_SLAB",
    "Bookcase": "ITEM_BOOKCASE",
    "TractionBench": "ITEM_TRACTION_BENCH",
}

WORKSHOP = {
    "Carpenters": "CARPENTER", "Farmers": "FARMER", "Masons": "MASON",
    "Craftsdwarfs": "CRAFTS", "Jewelers": "JEWELER",
    "MetalsmithsForge": "METALSMITH", "MagmaForge": "MAGMAFORGE",
    "Bowyers": "BOWYER", "Mechanics": "MECHANIC", "Siege": "SIEGE",
    "Butchers": "BUTCHER", "Leatherworks": "LEATHER", "Tanners": "TANNER",
    "Clothiers": "CLOTHES", "Fishery": "FISHERY", "Still": "STILL",
    "Loom": "LOOM", "Quern": "QUERN", "Kennels": "KENNEL",
    "Kitchen": "KITCHEN", "Ashery": "ASHERY", "Dyers": "DYER",
    "Millstone": "MILLSTONE",
}

FURNACE = {
    "WoodFurnace": "WOOD", "Smelter": "SMELTER", "MagmaSmelter": "SMELTER_LAVA",
    "GlassFurnace": "GLASS", "MagmaGlassFurnace": "GLASS_LAVA",
    "Kiln": "KILN", "MagmaKiln": "KILN_LAVA",
}


def _enum(table: dict, value: int, default: str = "") -> str:
    return str(table.get(str(value), table.get(value, default)))


def _pick(tokens: set[str], *candidates: str | None) -> str | None:
    return next((c for c in candidates if c and c in tokens), None)


def _family_fallback(tokens: set[str], prefix: str) -> str | None:
    bad = ("DAMAGE", "DAMAGED", "BLOOD", "VOMIT", "MUD", "WATER", "DEBRIS",
           "FORBIDDEN", "SPIKES", "RINGS", "STUDS", "ENGRAVING", "OVERLAY")
    choices = [t for t in tokens if (t == prefix or t.startswith(prefix + "_"))
               and not any(word in t for word in bad)]
    return min(choices, key=lambda t: (t.count("_"), len(t), t)) if choices else None


def item_token(item: list, enums: dict, tokens: set[str]) -> str | None:
    """Choose the normal, undamaged on-map sprite for a captured item."""
    name = _enum(enums.get("item", {}), item[1] if len(item) > 1 else -1)
    if not name or name == "NONE":
        return None
    cls = MATERIAL.get(item[10] if len(item) > 10 else 0)
    prefix = "ITEM_" + re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")
    aliases = {
        "ITEM_ARMORSTAND": "ITEM_ARMOR_STAND",
        "ITEM_WEAPONRACK": "ITEM_WEAPON_RACK",
        "ITEM_HATCH_COVER": "ITEM_HATCH",
        "ITEM_TRACTION_BENCH": "ITEM_TRACTION_BENCH",
    }
    prefix = aliases.get(prefix, prefix)
    raw = item[12] if len(item) > 12 else ""
    if raw and name in ("FISH", "FISH_RAW", "CORPSE", "CORPSEPIECE", "REMAINS"):
        creature = "CREATURE_" + re.sub(r"[^A-Z0-9_]+", "_", str(raw).upper())
        if creature in tokens:
            return creature
    if name in ("CORPSEPIECE", "REMAINS") and "ITEM_REMAINS" in tokens:
        return "ITEM_REMAINS"
    return (_pick(tokens, f"{prefix}_{cls}" if cls else None, prefix)
            or _family_fallback(tokens, f"{prefix}_{cls}" if cls else prefix)
            or _family_fallback(tokens, prefix))


def creature_token(unit: list, tokens: set[str]) -> str | None:
    raw = unit[9] if len(unit) > 9 else ""
    candidate = "CREATURE_" + re.sub(r"[^A-Z0-9_]+", "_", str(raw).upper())
    if raw and candidate in tokens:
        return candidate
    citizen = bool(unit[7]) if len(unit) > 7 else False
    return "CREATURE_DWARF" if citizen and "CREATURE_DWARF" in tokens else None


def _stage(building: list) -> int:
    built = building[9] if len(building) > 9 else 3
    maximum = building[10] if len(building) > 10 else 3
    if built < 0:
        return 3
    if maximum and maximum > 0:
        return max(0, min(3, round(3 * built / maximum)))
    return max(0, min(3, built))


def building_cells(building: list, enums: dict, tokens: set[str]) -> list[tuple[int, int, str]]:
    """Return absolute (x, y, token) cells for furniture/workshops/furnaces."""
    if len(building) < 7:
        return []
    btype = _enum(enums.get("bld", {}), building[1])
    cls = MATERIAL.get(building[13] if len(building) > 13 else 0)
    x1, y1, x2, y2 = building[2:6]
    family = FURNITURE.get(btype)
    if family:
        candidates = [f"{family}_{cls}" if cls else None, family]
        if btype == "Weaponrack":
            candidates.insert(0, f"{family}_{cls}_EMPTY" if cls else None)
        elif btype == "Armorstand":
            candidates.insert(0, f"{family}_{cls}_EMPTY" if cls else None)
        tok = _pick(tokens, *candidates) or _family_fallback(tokens, family)
        return [(x1, y1, tok)] if tok else []
    if btype == "Wagon" and "WAGON_BLD" in tokens:
        return [((x1 + x2) // 2, (y1 + y2) // 2, "WAGON_BLD")]

    subtype = building[7] if len(building) > 7 else -1
    if btype == "Workshop":
        raw = _enum(enums.get("workshop", {}), subtype)
        base = WORKSHOP.get(raw)
        prefix = "WORKSHOP_" + base if base else None
    elif btype == "Furnace":
        raw = _enum(enums.get("furnace", {}), subtype)
        base = FURNACE.get(raw)
        prefix = "FURNACE_" + base if base else None
    else:
        return []
    if not prefix:
        return []

    stage = _stage(building)
    # The live 53.16 viewport exposes exactly one `building_one` texpos per footprint
    # cell. Its raw lookup is [stage][x][y+1]: rows 1..3 are the 3x3 footprint and row 0
    # is not displayed. The game registers the base and transparent detail as one final
    # building texture; our extracted atlas retains those source components, so emit
    # them consecutively for the same cell to reconstruct that single final texture.
    base_cells, detail_cells = [], []
    width, height = x2 - x1 + 1, y2 - y1 + 1
    for dy in range(height):
        for dx in range(width):
            raw_y = dy + 1
            for layer, target in (("", base_cells), ("_OVERLAY", detail_cells)):
                p = prefix + layer
                tok = _pick(tokens,
                            f"{p}_S{stage}_{dx}_{raw_y}",
                            f"{p}_S3_{dx}_{raw_y}",
                            f"{p}_S0_{dx}_{raw_y}")
                if tok:
                    target.append((x1 + dx, y1 + dy, tok))
    return base_cells + detail_cells


def liquid_token(encoded: int, tokens: set[str]) -> str | None:
    depth, magma = encoded & 7, bool(encoded & 8)
    if depth <= 0:
        return None
    if magma:
        band = 1 if depth <= 2 else 2 if depth <= 5 else 3
        return _pick(tokens, f"MAGMA_{band}", "MAGMA_3", "MAGMA_1")
    return _pick(tokens, "WATER")


def visible_tokens(entities: Iterable[list], selector, enums: dict,
                   tokens: set[str]) -> list[str]:
    """Small QA helper used by tests and asset audits."""
    return [tok for entity in entities if (tok := selector(entity, enums, tokens))]
