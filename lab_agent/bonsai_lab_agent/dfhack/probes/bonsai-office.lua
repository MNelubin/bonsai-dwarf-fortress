-- Build the manager an office, headlessly, and report every step.
--
-- Three API traps live here, all the same shape — one side of a two-sided link:
--   * a civzone needs `abstract = true` or constructBuilding simply fails
--   * extents must be cast through df.reinterpret_cast; a raw uint8_t array assigned
--     after construction silently does not take (quickfort/building.lua is the reference)
--   * `assigned_unit_id` does NOT make a dwarf own a room — dfhack.buildings.setOwner does
--
-- Idempotent: if the manager already owns a zone this reports and exits.

local w = df.global.world
local ent = df.global.plotinfo.main.fortress_entity

local function say(...) print(table.concat({...}, ' ')) end

-- ------------------------------------------------------------------ the manager
local mgr
for _, u in ipairs(dfhack.units.getCitizens(true)) do
    for _, np in ipairs(dfhack.units.getNoblePositions(u) or {}) do
        if np.position.code == 'MANAGER' then mgr = u end
    end
end
if not mgr then say('OFFICE fail: no manager seated'); return end
say('manager unit', mgr.id)

for _, b in ipairs(mgr.owned_buildings) do
    if b:getType() == df.building_type.Civzone then
        say('OFFICE already owned: building', b.id); return
    end
end

-- ------------------------------------------------------------------ a floor to build on
-- Anchor on the manager's own tile: it is by construction reachable, indoors-ish, and
-- on the same z-level as the rest of the fort, which a scan for "any floor" is not.
local px, py, pz = mgr.pos.x, mgr.pos.y, mgr.pos.z

local function is_floor(x, y, z)
    local ok, tt = pcall(function() return dfhack.maps.getTileType(x, y, z) end)
    if not ok or not tt then return false end
    local shape = df.tiletype.attrs[tt].shape
    return shape == df.tiletype_shape.FLOOR or shape == df.tiletype_shape.BOULDER
        or shape == df.tiletype_shape.PEBBLES
end

local function free_at(x, y, z)
    if not is_floor(x, y, z) then return false end
    if dfhack.buildings.findAtTile(xyz2pos(x, y, z)) then return false end
    return true
end

local cx, cy
for r = 1, 12 do
    for dx = -r, r do
        for dy = -r, r do
            if not cx and free_at(px + dx, py + dy, pz) then cx, cy = px + dx, py + dy end
        end
    end
    if cx then break end
end
if not cx then say('OFFICE fail: no free floor near manager'); return end
say('chair site', cx, cy, pz)

-- ------------------------------------------------------------------ the chair
-- A previous run may have left a Chair building half-constructed; reuse it rather than
-- trying to place a second one from the same item, which just fails.
local bld
for _, b in ipairs(w.buildings.all) do
    if b:getType() == df.building_type.Chair and b.z == pz then bld = b; break end
end

if not bld then
    -- Prefer a chair that already exists; the item a building IS has use == 0, so a
    -- filter that rejected everything held by a building could not find one a workshop
    -- had just made.
    local chair
    for _, it in ipairs(w.items.all) do
        if it:getType() == df.item_type.CHAIR and not it.flags.in_building
            and not it.flags.dump and not it.flags.forbid then
            chair = it; break
        end
    end
    if not chair then
        local mat = dfhack.matinfo.find('INORGANIC:MICROCLINE') or dfhack.matinfo.find('INORGANIC')
        local made = dfhack.items.createItem(mgr, df.item_type.CHAIR, -1,
            mat and mat.type or 0, mat and mat.index or -1)
        chair = type(made) == 'table' and made[1] or made
        say('chair created', chair and chair.id or 'FAILED')
    else
        say('chair found', chair.id)
    end
    if not chair then say('OFFICE fail: no chair'); return end

    bld = dfhack.buildings.constructBuilding {
        type = df.building_type.Chair, pos = xyz2pos(cx, cy, pz), items = { chair },
    }
end
say('chair building', bld and bld.id or 'FAILED')
if not bld then say('OFFICE fail: chair not placed'); return end

-- Finish the construction outright. Waiting for a dwarf to walk over and build it is a
-- second unrelated failure mode stacked on top of the one under test.
pcall(function() bld:setBuildStage(bld:getMaxBuildStage()) end)
pcall(function() bld.flags.exists = true end)
cx, cy = bld.x1, bld.y1
say('chair stage', bld:getBuildStage(), '/', bld:getMaxBuildStage(), 'at', cx, cy, pz)

-- ------------------------------------------------------------------ the zone
local x1, y1 = cx - 2, cy - 2
local x2, y2 = cx + 2, cy + 2
local zw, zh = x2 - x1 + 1, y2 - y1 + 1
local area = zw * zh
local ext = df.reinterpret_cast(df.building_extents_type, df.new('uint8_t', area))
for i = 0, area - 1 do ext[i] = 1 end

local zone = dfhack.buildings.constructBuilding {
    type = df.building_type.Civzone, subtype = df.civzone_type.Office,
    abstract = true, pos = xyz2pos(x1, y1, pz),
    width = zw, height = zh,
}
if not zone then say('OFFICE fail: zone not constructed'); return end
zone.room.extents = ext
zone.room.x, zone.room.y, zone.room.width, zone.room.height = x1, y1, zw, zh
-- copied field-for-field from a working office on a hand-played fort: spec_sub_flag
-- carries the zone's own active bit (there is no zone_flags on this build).
--
-- Do NOT pre-set assigned_unit_id here. setOwner early-returns `true` when the zone
-- already names that unit, so writing it first makes the call a no-op that reports
-- success while owned_buildings stays empty — the same one-sided-link trap as writing
-- an assignment's histfig without the entity link.
zone.spec_sub_flag.active = true
say('zone', zone.id, 'w=' .. zw, 'h=' .. zh, 'extents=' .. tostring(zone.room.extents ~= nil))

dfhack.buildings.setOwner(zone, mgr)
local owns = {}
for _, b in ipairs(mgr.owned_buildings) do
    owns[#owns + 1] = df.building_type[b:getType()] .. ':' .. b.id
end
say('OFFICE done owner_sees', table.concat(owns, ','))
