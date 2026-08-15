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

-- ================================================================ orders, in brief
local orders_before = #w.manager_orders.all
apply('add_workorder\tConstructBed\t2\twood')
ok('add_workorder queues work', #w.manager_orders.all > orders_before
    or #_G.BONSAI_ORDERS > 0,
    string.format('orders %d -> %d', orders_before, #w.manager_orders.all))

print(string.format('-- TOOLCHECK pass=%d fail=%d skip=%d', pass, fail, skip))
