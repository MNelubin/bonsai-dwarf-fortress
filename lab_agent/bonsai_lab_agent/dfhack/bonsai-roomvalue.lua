--@ module = true
-- What a room is worth, and what that is good enough for.
--
-- This is the objective function the offline design search optimises, so every part of it
-- had to be established rather than assumed. It has already been shipped wrong once: the
-- first version carried DFHack's `dfhack_room_quality_level` cutoffs
-- (0/100/250/500/1000/1500/2500/10000) as though they were v50's, and they are not.
--
-- ---------------------------------------------------------------- the value
--
--   * `getRoomValue` DOES NOT EXIST in v50. Grepping all 153 df-structures files for it
--     returns nothing, and DFHack's own Buildings::getRoomDescription has its entire body
--     commented out with "TODO: understand how this changes for v50".
--   * A civzone carries no value at all: getPersonalValue(owner), getPersonalValue(nil)
--     and getArchValue() are 0 on every one of them.
--   * DF only produces the number in its UI layer, per UNIT, in
--     view_sheets.curroom[df.demand_room.<kind>], recomputed every render frame while a
--     unit sheet is open. Useless as a scorer: it needs an owner and a live sheet.
--
-- But the number is exactly reproducible offline:
--
--     value = (extent cells that are set) + sum of getPersonalValue(nil) over the
--             buildings the zone contains
--
-- Validated against DF's own curroom on three independent rooms — a 5x5 office with a
-- throne and two beds (59), a 3x3 bedroom with one superior bed (32), and a bare 2x2
-- bedroom (4) — exact match on all three.
--
-- THAT BOUND CASHED OUT. The three validating rooms were outdoor patches at z=49 on
-- unsmoothed ground, and the per-tile term was assumed to be 1 per cell. It is not: see
-- TILE_VALUE below, measured underground against DF's own number. Smoothing is worth 4.
-- What is STILL outside the formula: engraving (no value measured, and
-- `df.global.world.engravings` does not exist on this build, so the vector has to be
-- found before it can be priced), grates, windows, and displayed items.
--
-- ---------------------------------------------------------------- the names
--
-- Read out of the game binary, not from a wiki: 29 contiguous strings, four ladders, in
-- descending order. Their LENGTHS differ — 7, 8, 8 and 6 — which is on its own enough to
-- refuse the legacy eight-entry cutoff table. v50 also renames the office ladder to
-- Study ("Splendid Office", "Throne Room", "Burial Chamber", "Mausoleum" and a bare
-- "Tomb" all return zero hits in the binary) and adds a `No X` bottom rung DFHack has
-- never had.
LADDER = {
    Office     = { 'Royal Throne Room', 'Opulent Throne Room', 'Splendid Study',
                   'Decent Study', 'Modest Study', 'Meager Study', 'No Study' },
    Bedroom    = { 'Royal Bedroom', 'Grand Bedroom', 'Great Bedroom', 'Fine Quarters',
                   'Decent Quarters', 'Modest Quarters', 'Meager Quarters',
                   'No Quarters' },
    DiningHall = { 'Royal Dining Room', 'Grand Dining Room', 'Great Dining Room',
                   'Fine Dining Room', 'Decent Dining Room', 'Modest Dining Room',
                   'Meager Dining Room', 'No Dining Room' },
    Tomb       = { 'Royal Mausoleum', 'Grand Mausoleum', 'Fine Tomb',
                   "Servant's Burial Chamber", 'Grave', 'No Tomb' },
}

-- WHICH VALUE EARNS WHICH NAME IS NOT KNOWN, and this module will not pretend otherwise.
-- DFHack's getRoomDescription is the only API that would say, and on this build it is the
-- stub: called live against a freshly made zone, with an owner and without one, it
-- returned "" both times. So the ladder above is names in order and nothing more.
LADDER_CUTOFFS_KNOWN = false

-- ---------------------------------------------------------------- what it is good for
--
-- The scale that actually matters is DF's own, and it is readable: every entity position
-- states the room value that rank demands. Read live from world.entities.all, so this is
-- the game's number, not a remembered one. "A bedroom good enough for a baron" is a
-- target the fort can be held to; "tier 3" was never one.
--
-- Recorded here as the fallback and as the thing the battery checks the live read
-- against. Measured 2026-08-15 on the dwarven civ of a v50 world.
DEMANDS = {
    { pos = 'captain',              office = 1,     bedroom = 1,     dining = 1,     tomb = 0 },
    { pos = 'manager',              office = 1,     bedroom = 0,     dining = 0,     tomb = 0 },
    { pos = 'bookkeeper',           office = 1,     bedroom = 0,     dining = 0,     tomb = 0 },
    { pos = 'general',              office = 500,   bedroom = 250,   dining = 250,   tomb = 1 },
    { pos = 'lieutenant',           office = 100,   bedroom = 100,   dining = 100,   tomb = 0 },
    { pos = 'sheriff',              office = 100,   bedroom = 100,   dining = 100,   tomb = 0 },
    { pos = 'captain of the guard', office = 250,   bedroom = 250,   dining = 250,   tomb = 0 },
    { pos = 'dungeon master',       office = 250,   bedroom = 250,   dining = 250,   tomb = 0 },
    { pos = 'mayor',                office = 500,   bedroom = 500,   dining = 500,   tomb = 0 },
    { pos = 'baron',                office = 500,   bedroom = 500,   dining = 500,   tomb = 500 },
    { pos = 'outpost liaison',      office = 1500,  bedroom = 1500,  dining = 1500,  tomb = 0 },
    { pos = 'diplomat',             office = 1500,  bedroom = 1500,  dining = 1500,  tomb = 0 },
    { pos = 'count',                office = 1500,  bedroom = 1500,  dining = 1500,  tomb = 1500 },
    { pos = 'duke',                 office = 2500,  bedroom = 2500,  dining = 2500,  tomb = 2500 },
    { pos = 'monarch',              office = 10000, bedroom = 10000, dining = 10000, tomb = 10000 },
}

-- Which DEMANDS column a live zone kind is judged by. A zone kind absent from this table
-- has no noble demand attached to it and is scored on raw value alone.
DEMAND_FIELD = {
    Office     = 'office',
    Bedroom    = 'bedroom',
    Dormitory  = 'bedroom',
    DiningHall = 'dining',
    Tomb       = 'tomb',
}

local FIELD_IN_DF = {
    office = 'required_office', bedroom = 'required_bedroom',
    dining = 'required_dining', tomb = 'required_tomb',
}

-- DF's own table, read from the world rather than trusted from the constant above.
function live_demands()
    local out, seen = {}, {}
    for _, ent in ipairs(df.global.world.entities.all) do
        pcall(function()
            for _, p in ipairs(ent.positions.own) do
                local name = p.name[0]
                if name and name ~= '' and not seen[name] then
                    local row = { pos = name }
                    local any = false
                    for k, f in pairs(FIELD_IN_DF) do
                        local v = p[f] or 0
                        row[k] = v
                        if v > 0 then any = true end
                    end
                    if any then
                        seen[name] = true
                        out[#out + 1] = row
                    end
                end
            end
        end)
    end
    return out
end

-- Every rank whose demand for this kind of room this value satisfies, and the highest
-- threshold among them. `nil` for kinds nobody demands.
function meets(kind, value, demands)
    local field = DEMAND_FIELD[kind]
    if not field then return nil, nil end
    local names, best = {}, 0
    for _, d in ipairs(demands or DEMANDS) do
        local need = d[field] or 0
        if need > 0 and value >= need then
            names[#names + 1] = d.pos
            if need > best then best = need end
        end
    end
    table.sort(names)
    return names, best
end

-- What one tile of a room is worth. NOT 1 per cell, which is what this module shipped
-- first and what its own docstring warned might be wrong.
--
-- Measured against DF's own `view_sheets.curroom` on a 2x2 owned bedroom at z=48, by
-- poisoning curroom to -777 and reopening the owner's sheet so a stale read could not
-- pass as a fresh one:
--
--     4 rough soil tiles                     DF said 4
--     1 of the 4 rewritten StoneFloorSmooth  DF said 7
--     restored to soil                       DF said 4 again
--
-- So a smoothed tile is worth 4 where a rough one is worth 1, and the terms add per
-- tile — swept separately over 0,1,2,3,4 smoothed of 4, DF answered 4, 7, 10, 13, 16.
-- The old formula therefore undercounted every finished room by 3 per tile, which for a
-- 5x5 study is 100 against 25.
--
-- Enum names verified live rather than remembered: `df.tiletype_special.SMOOTH` = 3 and
-- `StoneFloorSmooth` carries it; `df.tiletype_material.FEATURE` = 3 and `FeatureFloor1`
-- carries it. `df.tiletype.attrs[tt]` returns NUMBERS, so these are compared numerically.
-- Constructed floor/wall multipliers are the values DF applies to the underlying
-- material. The room workflow uses constructed floors for surface rooms, so treating
-- them as rough would reject a room the game values correctly. These are conservative
-- base-material values; furniture is still read from the actual built items.
TILE_VALUE = {
    rough = 1, smooth = 4, feature = 2,
    constructed_floor = 7, constructed_wall = 9,
}

-- What an ENGRAVING adds, by quality. A whole term the scorer was blind to.
--
-- Engravings do not live on the tile: an engraved floor is still `StoneFloorSmooth` with
-- special = SMOOTH, so a tiletype-only scorer cannot see one at all. They are records in
-- `df.global.world.event.engravings` (NOT `world.engravings`, which does not exist on this
-- build), matched to a tile by `pos` in all three axes.
--
-- Measured on an owned 2x2 bedroom worth 4, by adding ONE record and sweeping its quality
-- with the poison-and-reopen oracle: DF answered 14, 24, 34, 44, 54, 124, 74.
--
-- The ladder is NOT monotonic. Masterful (5) adds 120 and Artifact (6) adds 70. That is
-- surprising enough to be worth writing down rather than smoothing over; it was read twice.
ENGRAVING_VALUE = { [0] = 10, [1] = 20, [2] = 30, [3] = 40, [4] = 50, [5] = 120, [6] = 70 }

-- Index every engraving once per report rather than once per zone. The vector is short on
-- a young fort and thousands of records long on an old one, and rooms() walks every zone.
local function engraving_index()
    local by = {}
    pcall(function()
        for _, e in ipairs(df.global.world.event.engravings) do
            local k = e.pos.z * 1000000 + e.pos.y * 1000 + e.pos.x
            by[k] = (by[k] or 0) + (ENGRAVING_VALUE[e.quality] or 0)
        end
    end)
    return by
end

function tile_value(x, y, z, engravings)
    local v = TILE_VALUE.rough
    pcall(function()
        local tt = dfhack.maps.getTileType(x, y, z)
        if not tt then return end
        local a = df.tiletype.attrs[tt]
        if a.material == df.tiletype_material.CONSTRUCTION
            and a.shape == df.tiletype_shape.FLOOR then
            v = TILE_VALUE.constructed_floor
        elseif a.material == df.tiletype_material.CONSTRUCTION
            and a.shape == df.tiletype_shape.WALL then
            v = TILE_VALUE.constructed_wall
        elseif a.special == df.tiletype_special.SMOOTH then
            v = TILE_VALUE.smooth
        elseif a.material == df.tiletype_material.FEATURE then
            v = TILE_VALUE.feature
        end
    end)
    if engravings then
        v = v + (engravings[z * 1000000 + y * 1000 + x] or 0)
    end
    return v
end

-- What the zone's tiles are worth, and how many there are. The extent array is what DF
-- paints, and a zone's bounding box is not the same thing as its area.
--
-- A WALL inside the extent still counts — measured, DF prices it the same as a rough
-- floor — so a zone painted over bedrock is free value. That is DF's rule and this
-- function reports it faithfully; refusing to exploit it belongs to whatever generates
-- designs, not to the thing that measures them.
function zone_tiles(b, engravings)
    local value, cells = 0, 0
    local ok = pcall(function()
        local x0 = b.room.x ~= 0 and b.room.x or b.x1
        local y0 = b.room.y ~= 0 and b.room.y or b.y1
        local w = b.room.width > 0 and b.room.width or (b.x2 - b.x1 + 1)
        local h = b.room.height > 0 and b.room.height or (b.y2 - b.y1 + 1)
        for dy = 0, h - 1 do
            for dx = 0, w - 1 do
                if b.room.extents[dy * w + dx] ~= 0 then
                    cells = cells + 1
                    value = value + tile_value(x0 + dx, y0 + dy, b.z, engravings)
                end
            end
        end
    end)
    if not ok or cells == 0 then
        -- a zone with no extents still occupies its box
        cells = (b.x2 - b.x1 + 1) * (b.y2 - b.y1 + 1)
        value = 0
        for x = b.x1, b.x2 do
            for y = b.y1, b.y2 do value = value + tile_value(x, y, b.z, engravings) end
        end
    end
    return value, cells
end

-- The furniture DF says the zone contains. `contained_buildings` is maintained by the
-- game, so no spatial matching is needed — and getPersonalValue(nil) on a furniture
-- building equals dfhack.items.getValue of the item it is made of, measured exactly on
-- four pieces (ordinary throne 10, ordinary bed 10, well-crafted 14, superior 23).
function furniture_value(b)
    local total = 0
    pcall(function()
        for _, c in ipairs(b.contained_buildings) do
            local ok, v = pcall(function() return c:getPersonalValue(nil) end)
            if ok and type(v) == 'number' then total = total + v end
        end
    end)
    return total
end

function value_of(b, engravings)
    local tiles, cells = zone_tiles(b, engravings or engraving_index())
    local furniture = furniture_value(b)
    return tiles + furniture, tiles, furniture, cells
end

function rooms()
    local engravings = engraving_index()
    local demands = live_demands()
    if #demands == 0 then demands = DEMANDS end
    local out = {}
    for _, b in ipairs(df.global.world.buildings.all) do
        if b:getType() == df.building_type.Civzone then
            local kind = tostring(df.civzone_type[b:getSubtype()])
            local value, tiles, furniture, cells = value_of(b, engravings)
            local names, best = meets(kind, value, demands)
            out[#out + 1] = {
                id = b.id, kind = kind, value = value, tiles = tiles,
                furniture = furniture, cells = cells, owner = b.assigned_unit_id,
                serves = names, threshold = best,
            }
        end
    end
    return out
end

if dfhack_flags and dfhack_flags.module then return end

local want = tonumber((...))
local list = rooms()
table.sort(list, function(a, b) return a.value > b.value end)
for _, r in ipairs(list) do
    if not want or r.id == want then
        local serves = 'n/a'
        if r.serves then
            serves = #r.serves > 0
                and string.format('>=%d: %s', r.threshold, table.concat(r.serves, ','))
                or 'nobody'
        end
        print(string.format('zone %-4d %-14s value=%-5d (%d from %d tiles + %d furniture) '
            .. 'owner=%-6s serves %s',
            r.id, r.kind, r.value, r.tiles, r.cells, r.furniture,
            r.owner == -1 and 'none' or tostring(r.owner), serves))
    end
end
print(string.format('-- %d zones', #list))
