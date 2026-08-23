--@ module = true
-- Can the fort actually get to this? — tiles, items, buildings, and candidate sites.
--
-- Almost every silent failure in this project has been a reachability failure wearing a
-- different hat: designations on sealed rock that produced zero dig jobs, a shaft whose
-- head nobody could stand on, a farm plot sited where no crop grows, a workshop placed on
-- a spot that was never reached. Each was found by hand, late, after a verb had reported
-- success.
--
-- DF already answers the question, and cheaply. `dfhack.maps.getWalkableGroup(pos)`
-- returns a connectivity id: two tiles are mutually reachable exactly when they share the
-- same non-zero group. `canWalkBetween` is that comparison. So the primitive is free and
-- the only real work is asking the right question about the right tile.
--
-- The trap that made this necessary rather than obvious: **a wall is not walkable**, so a
-- dig target legitimately reports unreachable. Reading that as "digging is broken" cost a
-- day. What matters for a tile you intend to REMOVE is whether something NEXT to it can
-- be reached; what matters for a tile you intend to BUILD on is the tile itself.
--
--   bonsai-reach                 report the fort's connectivity and the standing sites
--   bonsai-reach tile X Y Z      one tile, both readings
--   bonsai-reach items           every claimable material and whether it can be fetched
--   bonsai-reach why [filter]    what DF said when a job was cancelled, in its own words

local NEIGHBOURS = {
    { 1, 0, 0 }, { -1, 0, 0 }, { 0, 1, 0 }, { 0, -1, 0 },
    { 1, 1, 0 }, { 1, -1, 0 }, { -1, 1, 0 }, { -1, -1, 0 },
    { 0, 0, 1 }, { 0, 0, -1 },
}

-- The walkable-connectivity id of a tile. 0 means "nothing can stand here" — a wall, open
-- air, the inside of solid rock.
function group(x, y, z)
    local ok, g = pcall(function()
        return dfhack.maps.getWalkableGroup(xyz2pos(x, y, z))
    end)
    return (ok and g) or 0
end

-- The connectivity ids the fort's own citizens are standing in. Anything sharing one of
-- these is reachable BY THEM, which is the only sense of "reachable" that matters: a
-- perfectly walkable island on the far side of a chasm is not.
function fort_groups()
    local groups, n = {}, 0
    for _, u in ipairs(dfhack.units.getCitizens(true)) do
        local g = group(u.pos.x, u.pos.y, u.pos.z)
        if g ~= 0 and not groups[g] then groups[g] = true; n = n + 1 end
    end
    return groups, n
end

-- Can a citizen stand on this tile?
function tile(x, y, z, groups)
    groups = groups or fort_groups()
    local g = group(x, y, z)
    return g ~= 0 and groups[g] == true, g
end

-- Can a citizen stand NEXT to this tile? This is the question for anything you mean to
-- dig out, build into, or otherwise act on from outside — the tile itself being unwalkable
-- is the normal case there, not a fault.
function adjacent(x, y, z, groups)
    groups = groups or fort_groups()
    for _, d in ipairs(NEIGHBOURS) do
        local okd = tile(x + d[1], y + d[2], z + d[3], groups)
        if okd then return true end
    end
    return false
end

-- Where an item effectively IS. One in a dwarf's pack or inside the wagon is at its
-- holder's feet, not at whatever coordinates the item struct still carries.
function item_pos(item)
    local u
    pcall(function() u = dfhack.items.getHolderUnit(item) end)
    if u then return u.pos.x, u.pos.y, u.pos.z end
    local b
    pcall(function() b = dfhack.items.getHolderBuilding(item) end)
    if b then return b.centerx, b.centery, b.z end
    return item.pos.x, item.pos.y, item.pos.z
end

-- Can the fort fetch this item? Reachability AND claimability, because an item that is
-- forbidden, already in a job, or another civilisation's property is just as unavailable
-- as one on the wrong side of a wall — and all four look identical from a count.
function item(item, groups)
    groups = groups or fort_groups()
    if item.flags.forbid then return false, 'forbidden' end
    if item.flags.dump then return false, 'marked for dumping' end
    if item.flags.removed or item.flags.garbage_collect then return false, 'removed' end
    if item.flags.in_job then return false, 'already claimed by a job' end
    if item.flags.foreign then return false, 'another civilisation owns it' end
    local x, y, z = item_pos(item)
    if adjacent(x, y, z, groups) or tile(x, y, z, groups) then return true end
    return false, string.format('unreachable at %d,%d,%d', x, y, z)
end

function building(b, groups)
    groups = groups or fort_groups()
    return tile(b.centerx, b.centery, b.z, groups)
        or adjacent(b.centerx, b.centery, b.z, groups)
end

-- Is this rectangle a place the fort could actually build on: every tile a free floor a
-- citizen can stand on, and nothing already there. Returns false plus the first tile that
-- fails, so a refusal can say WHY rather than just declining.
function site(x0, y0, z, width, height, groups)
    groups = groups or fort_groups()
    for x = x0, x0 + (width or 1) - 1 do
        for y = y0, y0 + (height or 1) - 1 do
            local ok, tt = pcall(function() return dfhack.maps.getTileType(x, y, z) end)
            if not (ok and tt) then return false, x, y, 'off map' end
            local shape = df.tiletype.attrs[tt].shape
            if shape ~= df.tiletype_shape.FLOOR
                and shape ~= df.tiletype_shape.BOULDER
                and shape ~= df.tiletype_shape.PEBBLES then
                return false, x, y, 'not a floor'
            end
            if dfhack.buildings.findAtTile(xyz2pos(x, y, z)) then
                return false, x, y, 'occupied'
            end
            if not tile(x, y, z, groups) then
                return false, x, y, 'unreachable'
            end
        end
    end
    return true
end

-- The same rectangle question for something you mean to DIG rather than build on.
--
-- `site` demands a free floor a citizen can stand on, which is right for a workshop, a
-- stockpile or a zone and exactly wrong for a `#dig` blueprint: a crypt is supposed to go
-- into solid rock. Asking the wrong one of these two made `apply_template` refuse every
-- dig design on a fort with plenty of stone — the same wall-is-not-walkable confusion,
-- one layer up, that cost a day when it was about single tiles.
--
-- So: every tile must be on the map and not already designated, nothing may be built
-- there, and at least one tile must be one a miner can reach from beside — otherwise the
-- designation is an orphan that generates no jobs.
function dig_site(x0, y0, z, width, height, groups, hard_only, entry_x, entry_y)
    groups = groups or fort_groups()
    -- ONE WAY IN IS ENOUGH, and the reason is the cascade: a miner standing beside the
    -- first tile cuts it, which puts him beside the next, and so on until the whole
    -- connected block is out. So this does not ask that every tile be reachable, or
    -- revealed, or even that the whole rectangle be rock — two rules that were tried and
    -- were both wrong. It asks for three things:
    --
    --   1. something to dig            at least one solid wall in the box
    --   2. a way in                    one wall tile with an ORTHOGONALLY adjacent tile a
    --                                  citizen can stand on. Orthogonal and not diagonal:
    --                                  a miner works from the side, so a box touching the
    --                                  fort only at a corner has no entrance at all, and
    --                                  `adjacent()` counts diagonals and would call it one
    --   3. no air pocket splitting it  the wall tiles must form ONE 4-connected group, or
    --                                  the far part is a separate room the cascade never
    --                                  reaches
    local ORTHO = { { 1, 0 }, { -1, 0 }, { 0, 1 }, { 0, -1 } }
    local w = width or 1
    local h = height or 1
    local wall, entry = {}, false
    local nwall = 0
    for x = x0, x0 + w - 1 do
        for y = y0, y0 + h - 1 do
            local ok, tt = pcall(function() return dfhack.maps.getTileType(x, y, z) end)
            if not (ok and tt) then return false, x, y, 'off map' end
            local ok2, des = pcall(function() return dfhack.maps.getTileFlags(x, y, z) end)
            if ok2 and des and des.dig ~= df.tile_dig_designation.No then
                return false, x, y, 'already designated'
            end
            if dfhack.buildings.findAtTile(xyz2pos(x, y, z)) then
                return false, x, y, 'occupied'
            end
            -- Solid rock throughout. A room is carved out of stone in one piece; a box
            -- that is half open floor gets the open cells refused and leaves a design
            -- half-stamped, which is what "1 designated, 2 could not be" looked like.
            -- Being HIDDEN is fine and is not checked: a player designates into the dark
            -- all the time, and the cascade reveals as it goes.
            if df.tiletype.attrs[tt].shape ~= df.tiletype_shape.WALL then
                return false, x, y, 'not solid rock, so a room cannot be carved here'
            end
            if hard_only then
                local mat = df.tiletype.attrs[tt].material
                local hard = mat == df.tiletype_material.STONE
                    or mat == df.tiletype_material.MINERAL
                    or mat == df.tiletype_material.FEATURE
                    or mat == df.tiletype_material.LAVA_STONE
                    or mat == df.tiletype_material.FROZEN_LIQUID
                if not hard then
                    return false, x, y,
                        'the design needs smoothing, but this wall is soil or another soft material'
                end
            end
            wall[x .. ',' .. y] = true
            nwall = nwall + 1
            -- THE ENTRANCE MUST BE A TILE A MINER CAN ACTUALLY START ON: orthogonally
            -- beside standable ground, and NOT HIDDEN. Measured twice — a box whose
            -- designated cells were all hidden sat for 55,000 frames with zero dig jobs,
            -- through 15 miners and a priority bump, while an identical room cut off a
            -- known corridor face went in 15,000. DF does not dispatch to rock the fort
            -- has never seen.
            --
            -- Only the FIRST tile needs to be visible, though, which is the whole point of
            -- the cascade: cutting it reveals its neighbours, so they become diggable in
            -- turn. Requiring the whole box to be revealed was tried and refused every
            -- site on the map, because only a thin shell around the corridors is known.
            -- A generated room does not dig its whole bounding box: its perimeter is
            -- deliberately left as rock and only the doorway opens to the corridor.
            -- If the caller knows that doorway offset, it MUST be the reachable tile.
            -- Accepting some unrelated perimeter wall here produced a perfect-looking
            -- site whose three real dig cells were sealed behind rock forever.
            local is_entry = entry_x == nil
                or (x == x0 + entry_x and y == y0 + entry_y)
            if not entry and is_entry then
                local okh, dh = pcall(function() return dfhack.maps.getTileFlags(x, y, z) end)
                local visible = not (okh and dh and dh.hidden)
                if visible then
                    for _, d in ipairs(ORTHO) do
                        if tile(x + d[1], y + d[2], z, groups) then entry = true end
                    end
                end
            end
        end
    end
    if nwall == 0 then return false, x0, y0, 'nothing here to dig' end
    if not entry then
        return false, x0, y0,
            'no visible tile a miner could start from; a corner or hidden rock is not one'
    end

    -- one connected block, so the cascade reaches all of it
    local first
    for k in pairs(wall) do if not first or k < first then first = k end end
    local seen, stack, n = { [first] = true }, { first }, 1
    while #stack > 0 do
        local k = table.remove(stack)
        local cx, cy = k:match('^(-?%d+),(-?%d+)$')
        cx, cy = tonumber(cx), tonumber(cy)
        for _, d in ipairs(ORTHO) do
            local nk = (cx + d[1]) .. ',' .. (cy + d[2])
            if wall[nk] and not seen[nk] then
                seen[nk] = true
                n = n + 1
                stack[#stack + 1] = nk
            end
        end
    end
    if n < nwall then
        return false, x0, y0, string.format(
            'the rock here is in %d pieces, so digging one does not open the rest',
            nwall - n + 1)
    end
    return true
end

-- How much of a set of designations the fort can currently act on. A batch that is all
-- pending is not necessarily wrong — the chamber below a shaft is unreachable until the
-- staircase above it is cut — but a batch that STAYS all pending is an orphan.
function designations(ox, oy, oz, radius, depth)
    local groups = fort_groups()
    local total, actionable = 0, 0
    for dz = 0, (depth or 10) do
        for dx = -(radius or 8), (radius or 8) do
            for dy = -(radius or 8), (radius or 8) do
                local x, y, z = ox + dx, oy + dy, oz - dz
                local ok, des = pcall(function() return dfhack.maps.getTileFlags(x, y, z) end)
                if ok and des and des.dig ~= df.tile_dig_designation.No then
                    total = total + 1
                    if adjacent(x, y, z, groups) then actionable = actionable + 1 end
                end
            end
        end
    end
    return total, actionable
end

-- Why DF refused. `world.status.announcements` carries a plain-language cancellation for
-- every job a dwarf picked up and could not finish — "cancels Brew drink from plant:
-- Needs unrotten plant", "cancels Carve up/down staircase: Inappropriate dig square".
--
-- This is the other half of availability and it was sitting there unread the whole time.
-- Reachability answers "can we get to it"; this answers "we tried, and here is what was
-- missing", in the game's own words. Three shapes of brew job were called malformed on
-- the strength of a silent cancellation before anyone thought to look here.
function cancellations(limit, filter)
    local out = {}
    local anns = df.global.world.status.announcements
    local n = #anns
    for i = math.max(0, n - (limit or 40)), n - 1 do
        local ok, text = pcall(function() return tostring(anns[i].text) end)
        if ok and text:match('cancels') then
            if not filter or text:lower():match(filter:lower()) then
                out[#out + 1] = text
            end
        end
    end
    return out
end

-- ---------------------------------------------------------------- command line
-- reqscript hands the caller this script's environment, so everything above
-- is declared global on purpose: a `local M = {}` table is invisible to it, and
-- the caller sees a module with no functions on it.
if dfhack_flags and dfhack_flags.module then return end

local args = { ... }
local groups, ngroups = fort_groups()

if args[1] == 'tile' then
    local x, y, z = tonumber(args[2]), tonumber(args[3]), tonumber(args[4])
    local standable, g = tile(x, y, z, groups)
    print(string.format('%d,%d,%d group=%d stand_on=%s reach_from_beside=%s',
        x, y, z, g, tostring(standable), tostring(adjacent(x, y, z, groups))))
    return
end

if args[1] == 'why' then
    local said = cancellations(60, args[2])
    if #said == 0 then print('no cancellations on record') end
    for _, line in ipairs(said) do print('  ' .. line) end
    return
end

if args[1] == 'items' then
    local kinds = { WOOD = true, BOULDER = true, PLANT = true, SEEDS = true, BARREL = true }
    local tally = {}
    for _, i in ipairs(df.global.world.items.all) do
        local t = tostring(df.item_type[i:getType()])
        if kinds[t] then
            local usable, why = item(i, groups)
            local key = t .. ' ' .. (usable and 'usable' or (why or 'no'))
            tally[key] = (tally[key] or 0) + 1
        end
    end
    local keys = {}
    for k in pairs(tally) do keys[#keys + 1] = k end
    table.sort(keys)
    for _, k in ipairs(keys) do print(string.format('%-44s %d', k, tally[k])) end
    return
end

print(string.format('citizens stand in %d walkable group(s)', ngroups))
local P = _G.BONSAI_PLACE
if P and P.dig then
    local ox, oy, oz = P.dig[1], P.dig[2], P.dig[3]
    local standable = tile(ox, oy, oz, groups)
    local total, actionable = designations(ox, oy, oz, 8, 10)
    print(string.format('shaft head %d,%d,%d stand_on=%s', ox, oy, oz, tostring(standable)))
    print(string.format('designations near it: %d, of which %d can be worked now',
        total, actionable))
end
local shops, reachable_shops = 0, 0
for _, b in ipairs(df.global.world.buildings.all) do
    if df.building_workshopst:is_instance(b) then
        shops = shops + 1
        if building(b, groups) then reachable_shops = reachable_shops + 1 end
    end
end
print(string.format('workshops: %d, reachable %d', shops, reachable_shops))

local said = cancellations(40)
if #said > 0 then
    local tally = {}
    for _, line in ipairs(said) do
        local reason = line:match('cancels [^:]+:%s*(.+)$') or line
        tally[reason] = (tally[reason] or 0) + 1
    end
    local keys = {}
    for k in pairs(tally) do keys[#keys + 1] = k end
    table.sort(keys, function(a, b) return tally[a] > tally[b] end)
    print("recent job cancellations, in DF's own words:")
    for i = 1, math.min(#keys, 6) do
        print(string.format('  %3d  %s', tally[keys[i]], keys[i]))
    end
end
