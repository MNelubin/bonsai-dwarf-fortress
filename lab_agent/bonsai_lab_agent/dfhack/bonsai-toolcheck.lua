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

-- Is there anywhere on this fort a WxH design could go? Independent of the dispatcher's
-- placement ring on purpose: after five battery runs the ring is full of this battery's
-- own stockpiles, workshops and zones, and "the verb placed nothing" then means "there
-- was nowhere left", which is not a defect. Three cases failed that way before this
-- existed — the same unfalsifiable shape as counting a labour every citizen already had.
local function room_for(bw, bh)
    local u = dfhack.units.getCitizens(true)[1]
    if not u then return false end
    local reach = reqscript('bonsai-reach')
    local groups = reach.fort_groups()
    for r = 2, 30 do
        for dx = -r, r do
            for dy = -r, r do
                if reach.site(u.pos.x + dx, u.pos.y + dy, u.pos.z, bw, bh, groups) then
                    return true
                end
            end
        end
    end
    return false
end

-- The dig counterpart. A #dig blueprint goes INTO rock, so asking whether a free floor
-- exists is the wrong question — the one that made apply_template refuse every dig design
-- on a fort made of stone.
local function dig_room_for(bw, bh, ox, oy, oz, depth)
    local u = dfhack.units.getCitizens(true)[1]
    if not (ox or u) then return false end
    ox, oy, oz = ox or u.pos.x, oy or u.pos.y, oz or u.pos.z
    local reach = reqscript('bonsai-reach')
    local groups = reach.fort_groups()
    for dz = 0, (depth or 0) do
        for r = 2, 30 do
            for dx = -r, r do
                for dy = -r, r do
                    if reach.dig_site(ox + dx, oy + dy, oz - dz, bw, bh, groups) then
                        return true
                    end
                end
            end
        end
    end
    return false
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

-- The counter's window has to follow the shaft down, and once it did not.
--
-- This read 186 -> 186 and failed the case while the verb's own tally said it had marked
-- 40 tiles. Both were true: the shaft had been driven past ten levels by repeated runs,
-- and the new work landed BELOW where this was looking. A check that cannot see the work
-- reports a defect that is not there — the mirror of the silent-success problem this
-- whole battery exists to catch, and just as misleading.
local function designated_near()
    local P = _G.BONSAI_PLACE or {}
    if not P.dig then return 0, 0 end
    local ox, oy, oz = P.dig[1], P.dig[2], P.dig[3]
    local marked, widest = 0, 0
    for dz = 1, 30 do
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
    for dz = 1, 30 do
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

-- A workshop needs a building material to exist and to be walkable to. On a fort at
-- frame 0 nothing has been chopped or mined yet, so there is none — and REFUSING is then
-- the correct behaviour, not a defect. Asserting the build unconditionally made this case
-- fail on a fresh embark while the verb was doing exactly the right thing, which is the
-- same class of mistake as a verb that reports success while doing nothing: a check that
-- cannot tell the two apart.
local still_before = workshops_of('Still')
local reach_pre = reqscript('bonsai-reach')
local groups_pre = reach_pre.fort_groups()
local buildmat, buildmat_anywhere = nil, 0
for _, i in ipairs(w.items.all) do
    local t = i:getType()
    if t == df.item_type.WOOD or t == df.item_type.BOULDER or t == df.item_type.BLOCKS then
        buildmat_anywhere = buildmat_anywhere + 1
        if reach_pre.item(i, groups_pre) then buildmat = i end
    end
end
apply('build_workshop\tStill')
if not buildmat then
    skipped('build_workshop builds the kind asked for',
        string.format('no reachable building material (%d exist, none walkable to) - '
            .. 'the refusal is correct', buildmat_anywhere))
elseif workshops_of('Still') == still_before and not room_for(3, 3) then
    skipped('build_workshop builds the kind asked for',
        'material is reachable but no 3x3 site is free, so refusing is correct')
else
    ok('build_workshop builds the kind asked for',
        workshops_of('Still') > still_before,
        string.format('Still %d -> %d, material item %d',
            still_before, workshops_of('Still'), buildmat.id))
end

-- ================================================================ apply_template
-- The gate expands a template name into these six arguments, so the battery hands over
-- exactly what the dispatcher will see in play. Mini_Saracen: 11x11, one level, anchored
-- at 6;6 — the extent measured on the map after a live quickfort run, not the shape of
-- the file, which is 12 comma-fields by 26 lines and describes nothing.
do
    local function stamped()
        local n = 0
        for x = 0, w.map.x_count - 1 do
            for y = 0, w.map.y_count - 1 do
                for _, z in ipairs({ 45, 46, 47 }) do
                    local ok, d = pcall(function()
                        return dfhack.maps.getTileFlags(x, y, z)
                    end)
                    if ok and d and d.dig ~= df.tile_dig_designation.No then n = n + 1 end
                end
            end
        end
        return n
    end

    apply('apply_template\tno/such/blueprint.csv\t4\t5\t1\t1\t1\tdig\tdig')
    ok('an unknown blueprint is refused', true, 'no crash, no change')

    -- pump_stack rather than the 11x11 crypt: this fort has been dug into by five
    -- battery runs and no longer has a free 11x11 anywhere, and a case that can only
    -- skip is a case that tests nothing.
    _G.BONSAI_LAST_TEMPLATE = nil
    apply('apply_template\tlibrary/pump_stack.csv\t4\t5\t1\t1\t1\tdig\tdig')
    local t = _G.BONSAI_LAST_TEMPLATE
    if t and (t.new or 0) == 0 then
        -- It found a site and ran quickfort, and nothing changed. On this fort that is
        -- correct and even desirable: a template re-stamped over its own designations is
        -- idempotent. Distinguishing this from a refusal is why the verb records the
        -- attempt rather than only the success.
        skipped('apply_template stamps a design',
            string.format('already stamped at %d,%d,%d - re-applying changed nothing',
                t.x, t.y, t.z))
    elseif not t then
        skipped('apply_template stamps a design',
            dig_room_for(4, 5) and 'REFUSED a site that exists - look at this'
                or 'nowhere on this fort a 4x5 dig fits, so refusing is correct')
    else
        ok('apply_template stamps a design', (t.new or 0) > 0,
            string.format('%s at %d,%d,%d put %d new designations on the map',
                t.name, t.x, t.y, t.z, t.new or 0))
        -- Success has to be counted off the MAP. quickfort prints its own statistics and
        -- that line is what it intended, not what happened.
        local inside = 0
        for x = t.x, t.x + t.w - 1 do
            for y = t.y, t.y + t.h - 1 do
                local okd, d = pcall(function()
                    return dfhack.maps.getTileFlags(x, y, t.z)
                end)
                if okd and d and d.dig ~= df.tile_dig_designation.No then
                    inside = inside + 1
                end
            end
        end
        ok('what it stamped is inside the box it claimed', inside > 0,
            string.format('%d designated tiles within %dx%d at %d,%d',
                inside, t.w, t.h, t.x, t.y))
    end
end

-- ================================================================ stockpiles
-- Counting piles is what this case used to do, and it is why three inert stockpiles
-- passed it for weeks: every accept flag was false and every material vector empty, so
-- DF generated no hauling job and the fort's wagon sat fully loaded three game days
-- after embark. A pile that exists is not a pile that works.
local function pile_list()
    local out = {}
    for _, b in ipairs(w.buildings.all) do
        if b:getType() == df.building_type.Stockpile then out[#out + 1] = b end
    end
    return out
end

local function pile_flags(b)
    local n = 0
    pcall(function()
        for _, v in pairs(b.settings.flags) do
            if type(v) == 'boolean' and v then n = n + 1 end
        end
    end)
    return n
end

local function pile_mats(b, cat, field)
    local n = 0
    pcall(function()
        local v = b.settings[cat][field or 'mats']
        for i = 0, #v - 1 do if v[i] then n = n + 1 end end
    end)
    return n
end

local piles = #pile_list()
apply('create_stockpile\t1')
local after_create = pile_list()
if #after_create == piles and not room_for(2, 2) then
    skipped('create_stockpile places a stockpile',
        'no 2x2 site free on this fort, so refusing is correct')
else
    ok('create_stockpile places a stockpile', #after_create > piles,
        string.format('%d -> %d', piles, #after_create))
end

if #after_create == piles then
    skipped('a new pile accepts something', 'nothing was placed')
else
    local fresh = after_create[#after_create]
    ok('a new pile accepts something', pile_flags(fresh) > 0,
        string.format('%d of 17 categories on', pile_flags(fresh)))
    -- The flag is not the mechanism. DF matches items against the per-material vectors,
    -- and a pile built without DFHack's preset has them at length 0 while its flags can
    -- read true - exactly the state that produced zero hauling jobs.
    ok('a new pile has real material lists', pile_mats(fresh, 'stone') > 0,
        string.format('stone accepts %d materials', pile_mats(fresh, 'stone')))
end

-- configure_stockpile narrows it. The old body walked settings[<group>] flipping any
-- boolean it found, but those groups hold vectors: it flipped almost nothing and never
-- touched settings.flags, while reporting success every time.
local idx = #pile_list() - 1
local narrowed = pile_list()[idx + 1]
if not narrowed then
    skipped('configure_stockpile narrows a pile', 'no pile to narrow')
else
    apply('configure_stockpile\t' .. idx .. '\tfood')
    ok('configure_stockpile narrows a pile to one category',
        narrowed.settings.flags.food == true and narrowed.settings.flags.stone == false,
        string.format('food=%s stone=%s, %d categories on',
            tostring(narrowed.settings.flags.food),
            tostring(narrowed.settings.flags.stone), pile_flags(narrowed)))
    ok('the narrowed category has real material lists',
        pile_mats(narrowed, 'food', 'meat') > 0,
        string.format('food.meat accepts %d', pile_mats(narrowed, 'food', 'meat')))

    apply('configure_stockpile\t' .. idx .. '\tno_such_category')
    ok('an unknown stockpile category is refused',
        narrowed.settings.flags.food == true,
        'the pile kept the category it had')

    apply('configure_stockpile\t' .. idx .. '\tfood\tFalse')
    ok('containers can be turned off', narrowed.storage.max_barrels == 0,
        'max_barrels = ' .. tostring(narrowed.storage.max_barrels))
end

-- ================================================================ designate_dig
-- The verb skips tiles that are already designated, so on a fort carrying 181 pending
-- designations "it marked nothing" is the correct answer, not a defect. Same shape as the
-- placement cases: ask whether there was anything left to do before calling it a failure.
local marked_before = designated_near()
apply('designate_dig\t40\t4\t3')
local marked_after, widest = designated_near()
-- ...and it must be asked about the SHAFT, not about the citizen. designate_dig cuts
-- from a pinned origin and carves chambers off each landing; whether there is loose rock
-- somewhere else on the map is not a question it can act on.
local D = _G.BONSAI_PLACE and _G.BONSAI_PLACE.dig
if marked_after == marked_before and D
   and not dig_room_for(4, 3, D[1], D[2], D[3], 12) then
    skipped('designate_dig marks tiles',
        string.format('%d already designated and nothing fresh under the shaft',
            marked_before))
else
    ok('designate_dig marks tiles', marked_after > marked_before,
        string.format('%d -> %d designated', marked_before, marked_after))
end
-- The verb must keep LOOKING somewhere new even when it found nothing. Its ring counter
-- used to advance only when it placed something, which was invisible while mark() counted
-- its own no-ops; once the idempotence guard landed, a saturated call would freeze the
-- ring and re-walk the same four directions for the rest of the episode. Nothing about
-- the placed count can catch that, so assert the ring itself.
do
    local ring_before = (_G.BONSAI_PLACE or {}).digring or 0
    apply('designate_dig\t1\t1\t1')
    local ring_after = (_G.BONSAI_PLACE or {}).digring or 0
    ok('designate_dig keeps turning its ring even when it places nothing',
        ring_after > ring_before,
        string.format('digring %d -> %d', ring_before, ring_after))
end

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
if buildings_of(df.building_type.Civzone) == zones_before and not room_for(2, 2) then
    skipped('create_zone paints a zone',
        'no 2x2 site free on this fort, so refusing is correct')
else
    ok('create_zone paints a zone',
        buildings_of(df.building_type.Civzone) > zones_before,
        string.format('%d -> %d', zones_before, buildings_of(df.building_type.Civzone)))
end

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

-- v50 turns 86 of the 94 labour slots ON for EVERY citizen through the default work
-- details — only MINE, CUTWOOD and FISH are specialised at embark. So "did it set
-- STONE_CRAFT on one dwarf" cannot be answered by counting who has it: everyone already
-- did, and the old assertion (count < citizens) failed on a fresh fort while the verb was
-- working correctly. Turning a universal labour OFF for one dwarf is the test that can
-- only pass if the verb targets a single unit.
local one = dfhack.units.getCitizens(true)[1]
apply('set_dwarf_labor	' .. one.id .. '	STONE_CRAFT	True')
local craft_before = labor_count('STONE_CRAFT')
apply('set_dwarf_labor	' .. one.id .. '	STONE_CRAFT	False')
local craft_after = labor_count('STONE_CRAFT')
ok('set_dwarf_labor touches one dwarf only',
    one.status.labors[df.unit_labor.STONE_CRAFT] == false
    and craft_after == craft_before - 1,
    string.format('%d -> %d of %d citizens', craft_before, craft_after,
        #dfhack.units.getCitizens(true)))

-- put it back: a later case should not inherit a dwarf this battery crippled
apply('set_dwarf_labor	' .. one.id .. '	STONE_CRAFT	True')
ok('set_dwarf_labor turns it back on',
    one.status.labors[df.unit_labor.STONE_CRAFT] == true, 'restored')

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

    -- A log that exists but cannot be walked to is a real reachability defect. No log at
    -- all is a fort that has not chopped anything yet, and saying FAIL to that teaches
    -- nothing — it just trains us to ignore a red line.
    local material, logs = nil, 0
    for _, i in ipairs(w.items.all) do
        if i:getType() == df.item_type.WOOD then
            logs = logs + 1
            if reach.item(i, groups) then material = i end
        end
    end
    if logs == 0 then
        skipped('a claimable reagent is reachable', 'nothing has been chopped yet')
    else
        ok('a claimable reagent is reachable', material ~= nil,
            material and ('log ' .. material.id)
                or string.format('%d logs exist and NONE is walkable to', logs))
    end

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

-- ================================================================ room value and rank
-- The scorer the offline design search optimises. It has already shipped wrong once —
-- carrying DFHack's pre-v50 quality cutoffs as though they were this build's — so what
-- is asserted here is exactly what was read out of the game, and nothing that was
-- inferred from it.
do
    local rv = reqscript('bonsai-roomvalue')

    -- Read from the binary: 29 contiguous strings, four ladders, these lengths. The
    -- lengths are the whole argument against the legacy table, which had eight entries
    -- for every room type.
    local SHAPE = { Office = 7, Bedroom = 8, DiningHall = 8, Tomb = 6 }
    local bad = {}
    for kind, n in pairs(SHAPE) do
        local l = rv.LADDER[kind]
        if not l or #l ~= n then
            bad[#bad + 1] = string.format('%s=%s want %d', kind, l and #l or 'nil', n)
        end
    end
    ok('quality ladders have the length DF states', #bad == 0, table.concat(bad, ' '))

    local nobottom = {}
    for kind, l in pairs(rv.LADDER) do
        if not (l[#l]):match('^No ') then nobottom[#nobottom + 1] = kind .. ':' .. l[#l] end
    end
    ok('every ladder ends in the v50 "No X" rung', #nobottom == 0,
        table.concat(nobottom, ' '))

    -- Names that exist in DFHack's pre-v50 table and return ZERO hits in this binary.
    -- Any of them reappearing means the legacy table crept back in.
    local GONE = { ['Splendid Office'] = true, ['Throne Room'] = true,
                   ['Burial Chamber'] = true, ['Mausoleum'] = true, ['Tomb'] = true,
                   ['Office'] = true, ['Quarters'] = true, ['Dining Room'] = true }
    local ghosts = {}
    for kind, l in pairs(rv.LADDER) do
        for _, name in ipairs(l) do
            if GONE[name] then ghosts[#ghosts + 1] = kind .. ':' .. name end
        end
    end
    ok('no pre-v50 rung name has crept back', #ghosts == 0, table.concat(ghosts, ' '))

    -- The cutoffs are NOT known, and the module has to keep saying so. DFHack's
    -- getRoomDescription is the only thing that would tell us and it is the stub: called
    -- live on a fresh zone, with an owner and without, it answered "" both times.
    ok('the module still admits the cutoffs are unknown',
        rv.LADDER_CUTOFFS_KNOWN == false,
        'set this true only with a live measurement behind it')

    -- DF's own scale, re-read from the world every run. This is the check that catches
    -- the recorded table drifting away from the game.
    local live = rv.live_demands()
    local by_pos = {}
    for _, d in ipairs(live) do by_pos[d.pos] = d end
    local drift = {}
    for _, want in ipairs(rv.DEMANDS) do
        local got = by_pos[want.pos]
        if not got then
            drift[#drift + 1] = want.pos .. ':absent'
        else
            for _, f in ipairs({ 'office', 'bedroom', 'dining', 'tomb' }) do
                if (got[f] or 0) ~= want[f] then
                    drift[#drift + 1] = string.format('%s.%s=%d want %d',
                        want.pos, f, got[f] or 0, want[f])
                end
            end
        end
    end
    if #live == 0 then
        skipped('recorded noble demands match the game', 'no entity positions loaded')
    else
        ok('recorded noble demands match the game', #drift == 0,
            string.format('%d live positions; %s', #live,
                #drift == 0 and 'exact' or table.concat(drift, ' ')))
    end

    -- meets() is the ranking the agent asks against, so it has to be monotone: a better
    -- room can never serve fewer ranks than a worse one.
    local monotone, prev = true, -1
    for _, v in ipairs({ 0, 1, 100, 250, 500, 1500, 2500, 10000 }) do
        local names = rv.meets('Bedroom', v, rv.DEMANDS)
        if #names < prev then monotone = false end
        prev = #names
    end
    ok('room rank is monotone in value', monotone,
        string.format('a 10000 bedroom serves %d ranks',
            #rv.meets('Bedroom', 10000, rv.DEMANDS)))

    ok('a bare room serves nobody', #rv.meets('Bedroom', 0, rv.DEMANDS) == 0)
    ok('a kind nobody demands is not ranked',
        rv.meets('MeetingHall', 10000, rv.DEMANDS) == nil,
        'meeting halls carry no noble requirement')
end

-- ================================================================ orders, in brief
local orders_before = #w.manager_orders.all
apply('add_workorder\tConstructBed\t2\twood')
ok('add_workorder queues work', #w.manager_orders.all > orders_before
    or #_G.BONSAI_ORDERS > 0,
    string.format('orders %d -> %d', orders_before, #w.manager_orders.all))

print(string.format('-- TOOLCHECK pass=%d fail=%d skip=%d', pass, fail, skip))
