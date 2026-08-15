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
-- WHAT THAT VALIDATION DOES NOT COVER, stated because it bounds every score returned:
-- all three rooms were outdoor patches at z=49 on unsmoothed ground, some tiles carrying
-- saplings or shrubs, on a fort with zero engravings. Not one dug-out fortress room was
-- measured. DF's own UI says smoothing, engraving, grates, windows, statues and displayed
-- items raise room value; none of that is in this formula, so a finished room will score
-- low here until the per-tile term is re-measured underground.
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

-- How many tiles the zone actually covers. The extent array is what DF paints, and a
-- zone's bounding box is not the same thing as its area.
function zone_tiles(b)
    local n = 0
    local ok = pcall(function()
        local w = b.x2 - b.x1 + 1
        local h = b.y2 - b.y1 + 1
        for i = 0, w * h - 1 do
            if b.room.extents[i] ~= 0 then n = n + 1 end
        end
    end)
    if not ok or n == 0 then
        -- a zone with no extents still occupies its box
        n = (b.x2 - b.x1 + 1) * (b.y2 - b.y1 + 1)
    end
    return n
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

function value_of(b)
    local tiles = zone_tiles(b)
    local furniture = furniture_value(b)
    return tiles + furniture, tiles, furniture
end

function rooms()
    local demands = live_demands()
    if #demands == 0 then demands = DEMANDS end
    local out = {}
    for _, b in ipairs(df.global.world.buildings.all) do
        if b:getType() == df.building_type.Civzone then
            local kind = tostring(df.civzone_type[b:getSubtype()])
            local value, tiles, furniture = value_of(b)
            local names, best = meets(kind, value, demands)
            out[#out + 1] = {
                id = b.id, kind = kind, value = value, tiles = tiles,
                furniture = furniture, owner = b.assigned_unit_id,
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
        print(string.format('zone %-4d %-14s value=%-5d (%d tiles + %d furniture) '
            .. 'owner=%-6s serves %s',
            r.id, r.kind, r.value, r.tiles, r.furniture,
            r.owner == -1 and 'none' or tostring(r.owner), serves))
    end
end
print(string.format('-- %d zones', #list))
