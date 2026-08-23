-- Read-only acceptance report for durable build_room workflows.
-- It reports game objects, never the dispatcher's success counter.
local output = (...) or ('/tmp/bonsai-roomcheck-' .. tostring(os.getenv('DFHACK_PORT') or 'x') .. '.log')
local fh = assert(io.open(output, 'w'))
local function say(line) fh:write(line, '\n') end
local rows = {}
pcall(function() rows = dfhack.persistent.getSiteData('bonsai/room-workflows-v1') or {} end)
local bp = require('plugins.buildingplan')
local ids = {}
for id in pairs(rows) do ids[#ids + 1] = id end
table.sort(ids)

local TYPES = {
    [df.building_type.Armorstand]='a', [df.building_type.Bed]='b',
    [df.building_type.Chair]='c', [df.building_type.Door]='d',
    [df.building_type.Cabinet]='f', [df.building_type.Box]='h',
    [df.building_type.Coffin]='n', [df.building_type.Weaponrack]='r',
    [df.building_type.Statue]='s', [df.building_type.Table]='t',
}

local function built(b)
    local ok, stage, max = pcall(function() return b:getBuildStage(), b:getMaxBuildStage() end)
    return ok and max > 0 and stage >= max
end

for _, id in ipairs(ids) do
    local r = rows[id]
    local zone_count, zone, pieces, planned = 0, nil, {}, 0
    local shell_walls, shell_floors = 0, 0
    if r.x then
        for _, b in ipairs(df.global.world.buildings.all) do
            local in_box = b.z == r.z and b.x1 >= r.x and b.x1 < r.x + r.w
                and b.y1 >= r.y and b.y1 < r.y + r.h
            if in_box then
                if bp.isPlannedBuilding(b) then planned = planned + 1 end
                local key = TYPES[b:getType()]
                if key and built(b) then pieces[key] = (pieces[key] or 0) + 1 end
            end
            if b:getType() == df.building_type.Civzone and b:getSubtype() == df.civzone_type[r.kind]
                and b.z == r.z and b.x1 == r.x + r.zx and b.y1 == r.y + r.zy
                and b.x2 == r.x + r.zx + r.zw - 1
                and b.y2 == r.y + r.zy + r.zh - 1 then
                zone_count, zone = zone_count + 1, b
            end
        end
        for x = r.x, r.x + r.w - 1 do
            for y = r.y, r.y + r.h - 1 do
                local tt = dfhack.maps.getTileType(x, y, r.z)
                if tt then
                    local a = df.tiletype.attrs[tt]
                    if a.material == df.tiletype_material.CONSTRUCTION then
                        if a.shape == df.tiletype_shape.WALL then shell_walls = shell_walls + 1 end
                        if a.shape == df.tiletype_shape.FLOOR then shell_floors = shell_floors + 1 end
                    end
                end
            end
        end
    end
    local plist = {}
    for key, n in pairs(pieces) do plist[#plist + 1] = key .. ':' .. n end
    table.sort(plist)
    local value, owner = -1, -1
    if zone then
        owner = zone.assigned_unit_id
        pcall(function()
            value = select(1, reqscript('bonsai-roomvalue').value_of(zone))
        end)
    end
    say(string.format(
        'ROOM id=%s state=%s reason=%s strategy=%s pos=%s,%s,%s zones=%d owner=%d '
        .. 'value=%d/%d pieces=%s planned=%d shell=%d/%d,%d/%d',
        id, tostring(r.state), tostring(r.reason), tostring(r.strategy),
        tostring(r.x), tostring(r.y), tostring(r.z), zone_count, owner,
        value, tonumber(r.demand) or 0, table.concat(plist, ','), planned,
        shell_walls, tonumber(r.walls) or 0, shell_floors, tonumber(r.floors) or 0))
end
say(string.format('-- %d room workflow(s)', #ids))
fh:close()
