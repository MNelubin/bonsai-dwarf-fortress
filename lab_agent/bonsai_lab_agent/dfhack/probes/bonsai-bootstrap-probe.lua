-- Compact evidence for fresh-embark dependency debugging. Writes to a file because
-- dfhack-run stdout is not reliable while a fast headless episode is being paused.
local out = io.open('/tmp/bonsai-bootstrap-probe.log', 'w')
if not out then qerror('cannot open bootstrap probe log') end
local function say(s) out:write(s, '\n') end

local p = _G.BONSAI_PLACE or {}
local origin = p.dig
local citizens = 0
for _, unit in ipairs(df.global.world.units.active) do
    if dfhack.units.isCitizen(unit) then citizens = citizens + 1 end
end
say(string.format('world fortress=%s year=%d tick=%d frame=%d citizens=%d buildings=%d',
    tostring(dfhack.world.isFortressMode()), df.global.cur_year,
    df.global.cur_year_tick, df.global.world.frame_counter, citizens,
    #df.global.world.buildings.all))
if not dfhack.world.isFortressMode() then
    say('focus ' .. table.concat(dfhack.gui.getCurFocus(true), ','))
    local gps, screen = df.global.gps, dfhack.screen
    for y = 0, (tonumber(gps.dimy) or 64) - 1 do
        local chars = {}
        for x = 0, (tonumber(gps.dimx) or 128) - 1 do
            local ok, tile = pcall(function() return screen.readTile(x, y) end)
            local ch = ok and tile and tile.ch or 32
            chars[#chars + 1] = string.char(ch >= 32 and ch < 127 and ch or 32)
        end
        local row = table.concat(chars):match('^%s*(.-)%s*$')
        if row ~= '' then say('screen ' .. row) end
    end
end
say(string.format('pump active=%s generation=%s error=%s run_error=%s visits=%s last_made=%s orders=%d',
    tostring(_G.BONSAI_ORDER_PUMP_ACTIVE),
    tostring(_G.BONSAI_ORDER_PUMP_GENERATION),
    tostring(_G.BONSAI_ORDER_PUMP_ERROR),
    tostring(_G.BONSAI_RUN_PUMP_ERROR),
    tostring(_G.BONSAI_ORDER_PUMP_VISITS),
    tostring(_G.BONSAI_ORDER_PUMP_LAST_MADE),
    #(_G.BONSAI_ORDERS or {})))

local bp = require('plugins.buildingplan')
for _, building in ipairs(df.global.world.buildings.all) do
    if df.building_workshopst:is_instance(building) then
        say(string.format('workshop id=%d type=%s stage=%d/%d planned=%s jobs=%d',
            building.id, tostring(df.workshop_type[building.type]),
            building:getBuildStage(), building:getMaxBuildStage(),
            tostring(bp.isPlannedBuilding(building)), #building.jobs))
    end
end

if origin then
    say(string.format('shaft x=%d y=%d z=%d ring=%s',
        origin[1], origin[2], origin[3], tostring(p.digring)))
    for dz = 0, 30 do
        local z = origin[3] - dz
        local tt = dfhack.maps.getTileType(origin[1], origin[2], z)
        if tt then
            local a = df.tiletype.attrs[tt]
            local des = dfhack.maps.getTileFlags(origin[1], origin[2], z)
            local block = dfhack.maps.getTileBlock(origin[1], origin[2], z)
            say(string.format('layer dz=%d z=%d type=%s shape=%s material=%s dig=%s block_designated=%s',
                dz, z, tostring(df.tiletype[tt]),
                tostring(df.tiletype_shape[a.shape]),
                tostring(df.tiletype_material[a.material]),
                tostring(des and df.tile_dig_designation[des.dig]),
                tostring(block and block.flags.designated)))
        end
    end
else
    say('shaft none')
end

local names = { BED = true, BOULDER = true, STATUE = true, WOOD = true }
local count = {}
for name in pairs(names) do count[name] = { total=0, free=0, job=0, building=0 } end
for _, item in ipairs(df.global.world.items.all) do
    local name = tostring(df.item_type[item:getType()])
    local c = count[name]
    if c and not item.flags.foreign then
        c.total = c.total + 1
        if item.flags.in_job then c.job = c.job + 1 end
        if item.flags.in_building then c.building = c.building + 1 end
        if not (item.flags.in_job or item.flags.in_building or item.flags.forbid
                or item.flags.removed) then c.free = c.free + 1 end
    end
end
for _, name in ipairs{'BED', 'BOULDER', 'STATUE', 'WOOD'} do
    local c = count[name]
    say(string.format('item %s total=%d free=%d in_job=%d in_building=%d',
        name, c.total, c.free, c.job, c.building))
end

local link = df.global.world.jobs.list.next
while link do
    local job = link.item
    say(string.format('job id=%d type=%s order=%d items=%d', job.id,
        tostring(df.job_type[job.job_type]), job.order_id, #job.items))
    link = link.next
end
out:close()
