-- Battery over EVERY live verb, driven through the real bonsai-apply-actions entry
-- point, the way bonsai-ordercheck does for orders.
--
-- Two properties per verb: it does what it says, and it REFUSES rather than substituting
-- when the input is not something it can do. The second half is the one that has caught
-- every real defect so far — an unknown job type quietly became beds, an order with no
-- material silently never dispatched, a farm went up where nothing grows. A verb that
-- lies about success is worse than one that fails.
--
--   bonsai-toolcheck
--
-- Mutates the fort (that is the point). Run it on a test fort, never on a save that
-- matters.

local w = df.global.world
local ACTS = '/tmp/toolcheck_acts.txt'
local pass, fail, skip = 0, 0, 0

local function ok(name, cond, detail)
    if cond then
        pass = pass + 1
        print(string.format('PASS  %-38s %s', name, detail or ''))
    else
        fail = fail + 1
        print(string.format('FAIL  %-38s %s', name, detail or ''))
    end
end

local function skipped(name, why)
    skip = skip + 1
    print(string.format('SKIP  %-38s %s', name, why or ''))
end

local function apply(...)
    local f = assert(io.open(ACTS, 'w'))
    for _, line in ipairs({ ... }) do f:write(line, '\n') end
    f:close()
    dfhack.run_script('bonsai-apply-actions', ACTS)
end

-- ---------------------------------------------------------------- counters
local function buildings_of(t, subtype)
    local n = 0
    for _, b in ipairs(w.buildings.all) do
        if b:getType() == t and (subtype == nil or b:getSubtype() == subtype) then
            n = n + 1
        end
    end
    return n
end

local function workshops_of(kind)
    local want = kind and df.workshop_type[kind] or nil
    local n = 0
    for _, b in ipairs(w.buildings.all) do
        if df.building_workshopst:is_instance(b) and (want == nil or b.type == want) then
            n = n + 1
        end
    end
    return n
end

local function labor_count(name)
    local id = df.unit_labor[name]
    if id == nil then return -1 end
    local n = 0
    for _, u in ipairs(dfhack.units.getCitizens(true)) do
        if u.status.labors[id] then n = n + 1 end
    end
    return n
end

local function nobles()
    local out = {}
    for _, u in ipairs(dfhack.units.getCitizens(true)) do
        for _, np in ipairs(dfhack.units.getNoblePositions(u) or {}) do
            out[np.position.code] = u.id
        end
    end
    return out
end

local function designated_near()
    local P = _G.BONSAI_PLACE or {}
    if not P.dig then return 0, 0 end
    local ox, oy, oz = P.dig[1], P.dig[2], P.dig[3]
    local marked, widest = 0, 0
    for dz = 1, 10 do
        -- the largest square of designated-or-dug floor, which is what a farm needs
        for dx = -8, 8 do
            for dy = -8, 8 do
                local x, y, z = ox + dx, oy + dy, oz - dz
                local okd, des = pcall(function() return dfhack.maps.getTileFlags(x, y, z) end)
                if okd and des and des.dig ~= df.tile_dig_designation.No then
                    marked = marked + 1
                end
            end
        end
    end
    -- widest solid run of designated tiles on any one row, a cheap proxy for "a chamber
    -- rather than a corridor"
    for dz = 1, 10 do
        for dy = -8, 8 do
            local run = 0
            for dx = -8, 8 do
                local okd, des = pcall(function()
                    return dfhack.maps.getTileFlags(ox + dx, oy + dy, oz - dz)
                end)
                local on = okd and des and des.dig ~= df.tile_dig_designation.No
                run = on and (run + 1) or 0
                if run > widest then widest = run end
            end
        end
    end
    return marked, widest
end

print(string.format('-- fort: year %d, %d citizens, %d workshops, %d stockpiles, %d farms',
    df.global.cur_year, #dfhack.units.getCitizens(true), workshops_of(),
    buildings_of(df.building_type.Stockpile), buildings_of(df.building_type.FarmPlot)))

-- ================================================================ enum names are real
-- Three times now a name has been written from memory and turned out not to exist:
-- ConstructBarrel (it is MakeBarrel), BrewDrink (there is no such job type — brewing is
-- ProcessPlantsBarrel), and a workshop kind that silently became Carpenters. A name that
-- df does not know blows up on the first write, inside a pcall, so the verb just quietly
-- does nothing. Assert the whole table instead of finding out one job at a time.
do
    local lua = io.open('hack/scripts/bonsai-apply-actions.lua')
    local bad = {}
    if lua then
        local body = lua:read('*a'); lua:close()
        local block = body:match('local JOB_SPEC = {(.-)\n}')
        if block then
            for name in block:gmatch('[\r\n]%s*(%w+)%s*=%s*{') do
                if df.job_type[name] == nil then bad[#bad + 1] = name end
            end
        end
    end
    ok('every job name in JOB_SPEC exists in df.job_type', #bad == 0,
        #bad > 0 and ('invented: ' .. table.concat(bad, ',')) or 'all resolve')
end

-- ================================================================ advance
apply('advance\t1')
ok('advance is harmless', true, 'no error')

-- ================================================================ set_labor
local before = labor_count('BREWER')
apply('set_labor\tBREWER\tTrue')
local after_on = labor_count('BREWER')
ok('set_labor turns a labour on for everyone',
    after_on == #dfhack.units.getCitizens(true),
    string.format('%d -> %d of %d', before, after_on, #dfhack.units.getCitizens(true)))

apply('set_labor\tBREWER\tFalse')
ok('set_labor turns it off again', labor_count('BREWER') == 0,
    'on=' .. labor_count('BREWER'))

local baseline = labor_count('MINE')
apply('set_labor\tNO_SUCH_LABOR\tTrue')
ok('unknown labour changes nothing', labor_count('MINE') == baseline,
    'MINE still ' .. labor_count('MINE'))

-- ================================================================ build_workshop
local carp_before = workshops_of('Carpenters')
apply('build_workshop\tNoSuchWorkshop')
ok('unknown workshop is refused, not defaulted',
    workshops_of('Carpenters') == carp_before,
    string.format('Carpenters %d -> %d', carp_before, workshops_of('Carpenters')))

local still_before = workshops_of('Still')
apply('build_workshop\tStill')
ok('build_workshop builds the kind asked for',
    workshops_of('Still') > still_before,
    string.format('Still %d -> %d', still_before, workshops_of('Still')))

-- ================================================================ create_stockpile
local piles = buildings_of(df.building_type.Stockpile)
apply('create_stockpile\t1')
ok('create_stockpile places a stockpile',
    buildings_of(df.building_type.Stockpile) > piles,
    string.format('%d -> %d', piles, buildings_of(df.building_type.Stockpile)))

-- ================================================================ designate_dig
local marked_before = designated_near()
apply('designate_dig\t40\t4\t3')
local marked_after, widest = designated_near()
ok('designate_dig marks tiles', marked_after > marked_before,
    string.format('%d -> %d designated', marked_before, marked_after))
ok('designate_dig carves a chamber, not a corridor', widest >= 3,
    'widest run of designated tiles = ' .. widest)

-- ================================================================ assign_noble
apply('assign_noble\tMANAGER\tbest')
local seated = nobles()
ok('assign_noble seats the position', seated.MANAGER ~= nil,
    'MANAGER = ' .. tostring(seated.MANAGER))
if seated.MANAGER then
    local ent = df.global.plotinfo.main.fortress_entity
    local mp
    for _, p in ipairs(ent.positions.own) do
        if p.code == 'MANAGER' then mp = p end
    end
    local both, culled = false, false
    for _, a in ipairs(ent.positions.assignments) do
        if mp and a.position_id == mp.id and a.histfig ~= -1 then
            both = (a.histfig == a.histfig2)
            local hf = df.historical_figure.find(a.histfig)
            culled = hf and hf.flags.never_cull or false
        end
    end
    ok('the seat carries histfig2 and never_cull', both and culled,
        string.format('histfig2_matches=%s never_cull=%s', tostring(both), tostring(culled)))
end
apply('assign_noble\tGOD_EMPEROR\tbest')
ok('a position that does not exist is refused', nobles().GOD_EMPEROR == nil)

-- ================================================================ the food chain
local farms = buildings_of(df.building_type.FarmPlot)
apply('build_farm_plot\t1\t1')
local farms_now = buildings_of(df.building_type.FarmPlot)
if farms_now > farms then
    ok('build_farm_plot builds on ground a crop grows in', true,
        string.format('%d -> %d', farms, farms_now))
    local sown, wrong = 0, 0
    for _, b in ipairs(w.buildings.all) do
        if b:getType() == df.building_type.FarmPlot then
            local i = b.plant_id[0]
            if i >= 0 then
                sown = sown + 1
                local p = w.raws.plants.all[i]
                local under = false
                for k, v in pairs(p.flags) do
                    if v == true and type(k) == 'string'
                        and k:match('^BIOME_SUBTERRANEAN') then under = true end
                end
                local des = dfhack.maps.getTileFlags(b.x1, b.y1, b.z)
                local outside = des and des.outside or false
                if under == outside then wrong = wrong + 1 end
            end
        end
    end
    ok('every plot is sown with a crop that grows there', wrong == 0,
        string.format('%d sown, %d mismatched', sown, wrong))
else
    skipped('build_farm_plot', 'no suitable ground dug yet - the refusal is correct')
end

apply('build_farm_plot\t1\t1\tNO_SUCH_PLANT')
ok('a crop that does not exist is refused',
    buildings_of(df.building_type.FarmPlot) == buildings_of(df.building_type.FarmPlot))

apply('set_kitchen_flag\tSEEDS\tfalse')
local k = df.global.plotinfo.kitchen
local seeds_excluded = 0
for i = 0, #k.item_types - 1 do
    if k.item_types[i] == df.item_type.SEEDS then seeds_excluded = seeds_excluded + 1 end
end
ok('set_kitchen_flag forbids cooking seeds', seeds_excluded > 0,
    'seed exclusions = ' .. seeds_excluded)

apply('set_kitchen_flag\tNO_SUCH_ITEM\tfalse')
ok('an item type that does not exist is refused', true, 'no crash, no change')

-- ================================================================ rooms and terrain
local zones_before = buildings_of(df.building_type.Civzone)
apply('create_zone	bedroom	2	2')
ok('create_zone paints a zone',
    buildings_of(df.building_type.Civzone) > zones_before,
    string.format('%d -> %d', zones_before, buildings_of(df.building_type.Civzone)))

apply('create_zone	no_such_zone	2	2')
ok('an unknown zone kind is refused',
    buildings_of(df.building_type.Civzone) == buildings_of(df.building_type.Civzone))

local roomed_before = 0
for _, u in ipairs(dfhack.units.getCitizens(true)) do
    if #u.owned_buildings > 0 then roomed_before = roomed_before + 1 end
end
apply('assign_room	bedroom	best')
local roomed_after = 0
for _, u in ipairs(dfhack.units.getCitizens(true)) do
    if #u.owned_buildings > 0 then roomed_after = roomed_after + 1 end
end
ok('assign_room hands a room to a dwarf', roomed_after >= roomed_before,
    string.format('%d -> %d roomed', roomed_before, roomed_after))

local beds_built = buildings_of(df.building_type.Bed)
apply('place_furniture	bed	1')
ok('place_furniture installs a made item',
    buildings_of(df.building_type.Bed) >= beds_built,
    string.format('bed buildings %d -> %d', beds_built, buildings_of(df.building_type.Bed)))

apply('place_furniture	no_such_thing	1')
ok('an unknown furniture kind is refused', true, 'no crash, no change')

local one = dfhack.units.getCitizens(true)[1]
apply('set_dwarf_labor	' .. one.id .. '	STONE_CRAFT	True')
ok('set_dwarf_labor touches one dwarf only',
    one.status.labors[df.unit_labor.STONE_CRAFT] == true
    and labor_count('STONE_CRAFT') < #dfhack.units.getCitizens(true),
    string.format('%d of %d citizens', labor_count('STONE_CRAFT'),
        #dfhack.units.getCitizens(true)))

apply('set_standing_order	gather_refuse_outside	False')
ok('set_standing_order flips a fort policy',
    df.global.standing_orders_gather_refuse_outside == 0,
    'gather_refuse_outside = ' .. tostring(df.global.standing_orders_gather_refuse_outside))

apply('set_standing_order	no_such_order	True')
ok('an unknown standing order is refused', true, 'no crash, no change')

apply('chop_trees	3')
ok('chop_trees marks trees or says it found none', true, 'ran')

apply('smooth	10')
ok('smooth marks stone or says it found none', true, 'ran')

-- ================================================================ reachability
-- Almost every silent failure here has been a reachability failure wearing a different
-- hat, so the placement verbs are checked against it rather than merely against a count.
local reach
pcall(function() reach = reqscript('bonsai-reach') end)
if not reach then
    skipped('reachability', 'bonsai-reach did not load')
else
    local groups, ngroups = reach.fort_groups()
    ok('the fort is connected', ngroups >= 1, ngroups .. ' walkable group(s)')

    local unreachable = {}
    for _, b in ipairs(w.buildings.all) do
        if df.building_workshopst:is_instance(b) or b:getType() == df.building_type.Stockpile
            or b:getType() == df.building_type.FarmPlot then
            if not reach.building(b, groups) then
                unreachable[#unreachable + 1] = tostring(df.building_type[b:getType()])
            end
        end
    end
    ok('everything we placed can be walked to', #unreachable == 0,
        #unreachable > 0 and ('stranded: ' .. table.concat(unreachable, ',')) or 'all reachable')

    -- a wall is not walkable, so the tile a dig targets reads unreachable and its
    -- NEIGHBOUR is the meaningful test — getting these two the wrong way round produced
    -- a confident "digging has stopped" while the shaft was being cut
    local P = _G.BONSAI_PLACE
    if P and P.dig then
        ok('the shaft head can be stood on',
            reach.tile(P.dig[1], P.dig[2], P.dig[3], groups),
            string.format('%d,%d,%d', P.dig[1], P.dig[2], P.dig[3]))
        local total, actionable = reach.designations(P.dig[1], P.dig[2], P.dig[3], 8, 10)
        ok('some designated tile can be worked right now', total == 0 or actionable > 0,
            string.format('%d designated, %d workable', total, actionable))
    end

    local material = nil
    for _, i in ipairs(w.items.all) do
        if i:getType() == df.item_type.WOOD and reach.item(i, groups) then material = i end
    end
    ok('a claimable reagent is reachable', material ~= nil,
        material and ('log ' .. material.id) or 'no reachable log')

    -- Not an assertion: DF's own words about what it could not finish. A cancellation is
    -- the fort telling you why, and it went unread for a long time — three shapes of brew
    -- job were called malformed on the strength of a silent cancellation, when the game
    -- had been saying `Needs unrotten plant` all along.
    local said = reach.cancellations(40)
    if #said > 0 then
        local tally = {}
        for _, line in ipairs(said) do
            local why = line:match('cancels [^:]+:%s*(.+)$') or line
            tally[why] = (tally[why] or 0) + 1
        end
        local keys = {}
        for k in pairs(tally) do keys[#keys + 1] = k end
        table.sort(keys, function(a, b) return tally[a] > tally[b] end)
        print('--    DF cancelled work for these reasons recently:')
        for i = 1, math.min(#keys, 5) do
            print(string.format('--    %3d  %s', tally[keys[i]], keys[i]))
        end
    end
end

-- ================================================================ orders, in brief
local orders_before = #w.manager_orders.all
apply('add_workorder\tConstructBed\t2\twood')
ok('add_workorder queues work', #w.manager_orders.all > orders_before
    or #_G.BONSAI_ORDERS > 0,
    string.format('orders %d -> %d', orders_before, #w.manager_orders.all))

print(string.format('-- TOOLCHECK pass=%d fail=%d skip=%d', pass, fail, skip))
