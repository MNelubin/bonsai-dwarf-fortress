--@ module = true
-- What a room is worth, and which quality tier that reaches.
--
-- This is the objective function the offline design search optimises, so it had to be
-- established rather than assumed. Three things were found by investigating the game
-- instead of guessing at API names:
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
-- CAVEAT, stated because it bounds every score this returns: the per-tile term is
-- confirmed only for ROUGH floor. All three measured rooms were 100% unsmoothed and the
-- fort had zero engravings. DF's own UI says grates, windows, statues and displayed items
-- raise room value; none of that was measured, so a smoothed or engraved room will score
-- low here.
--
--   bonsai-roomvalue            every owned zone, its value and its tier
--   bonsai-roomvalue <id>       one zone

-- Thresholds are IDENTICAL across bedroom, dining room, office and tomb; only the names
-- differ. Confirmed across five wiki pages. The v50 source is `Zone § Quality and value` —
-- the main-namespace `Room` page is tagged obsolete, because as of v50.01 rooms are
-- activity zones.
TIERS = {
    { value = 10000, tier = 8 },
    { value = 2500,  tier = 7 },
    { value = 1500,  tier = 6 },
    { value = 1000,  tier = 5 },
    { value = 500,   tier = 4 },
    { value = 250,   tier = 3 },
    { value = 100,   tier = 2 },
    { value = 0,     tier = 1 },
}

TIER_NAMES = {
    Bedroom    = { 'Meager Quarters', 'Modest Quarters', 'Quarters', 'Decent Quarters',
                   'Fine Quarters', 'Great Bedroom', 'Grand Bedroom', 'Royal Bedroom' },
    DiningHall = { 'Meager Dining Room', 'Modest Dining Room', 'Dining Room',
                   'Decent Dining Room', 'Fine Dining Room', 'Great Dining Room',
                   'Grand Dining Room', 'Royal Dining Room' },
    Office     = { 'Meager Office', 'Modest Office', 'Office', 'Decent Office',
                   'Splendid Office', 'Throne Room', 'Opulent Throne Room',
                   'Royal Throne Room' },
    Tomb       = { 'Grave', "Servant's Burial Chamber", 'Burial Chamber', 'Tomb',
                   'Fine Tomb', 'Mausoleum', 'Grand Mausoleum', 'Royal Mausoleum' },
}

function tier_of(value)
    for _, t in ipairs(TIERS) do
        if value >= t.value then return t.tier end
    end
    return 1
end

function tier_name(kind, value)
    local names = TIER_NAMES[kind]
    if not names then return '' end
    return names[tier_of(value)] or ''
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
    local out = {}
    for _, b in ipairs(df.global.world.buildings.all) do
        if b:getType() == df.building_type.Civzone then
            local kind = tostring(df.civzone_type[b:getSubtype()])
            local value, tiles, furniture = value_of(b)
            out[#out + 1] = {
                id = b.id, kind = kind, value = value, tiles = tiles,
                furniture = furniture, tier = tier_of(value),
                name = tier_name(kind, value),
                owner = b.assigned_unit_id,
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
        print(string.format('zone %-4d %-14s value=%-5d (%d tiles + %d furniture) '
            .. 'tier=%d %-24s owner=%s',
            r.id, r.kind, r.value, r.tiles, r.furniture, r.tier, r.name,
            r.owner == -1 and 'none' or tostring(r.owner)))
    end
end
print(string.format('-- %d zones', #list))
