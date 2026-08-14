-- Battery of checks on the work-order tool, driven through the REAL entry point.
--
-- Every case writes an actions file and runs bonsai-apply-actions exactly as the episode
-- driver does, then inspects world state. Testing the internal functions directly would
-- miss the verb parsing, which is where one of the defects lives.
--
--   bonsai-ordercheck            run everything, print PASS/FAIL per case
--
-- Leaves the fort as it found it: orders created here are erased and the jobs they made
-- are removed, so it can be run repeatedly on a live test fort.

local w = df.global.world
local ACTS = '/tmp/ordercheck_acts.txt'

local pass, fail = 0, 0
local function ok(name, cond, detail)
    if cond then
        pass = pass + 1
        print(string.format('PASS  %-34s %s', name, detail or ''))
    else
        fail = fail + 1
        print(string.format('FAIL  %-34s %s', name, detail or ''))
    end
end

local function apply(...)
    local f = assert(io.open(ACTS, 'w'))
    for _, line in ipairs({ ... }) do f:write(line, '\n') end
    f:close()
    dfhack.run_script('bonsai-apply-actions', ACTS)
end

-- ---------------------------------------------------------------- world helpers
local function workshops()
    local t = {}
    for _, b in ipairs(w.buildings.all) do
        if df.building_workshopst:is_instance(b) then t[#t + 1] = b end
    end
    return t
end

local function manager_jobs()
    local t = {}
    for _, b in ipairs(workshops()) do
        for _, j in ipairs(b.jobs) do
            if j.flags.by_manager then t[#t + 1] = { job = j, shop = b } end
        end
    end
    return t
end

local function jobs_for(order_id, expect_item)
    local n, wrong_item, shops_used = 0, 0, {}
    local want = expect_item and df.item_type[expect_item] or nil
    for _, e in ipairs(manager_jobs()) do
        if e.job.order_id == order_id then
            n = n + 1
            shops_used[df.workshop_type[e.shop.type]] = true
            for _, it in ipairs(e.job.items) do
                if want and it.item and it.item:getType() ~= want then
                    wrong_item = wrong_item + 1
                end
            end
        end
    end
    local names = {}
    for k in pairs(shops_used) do names[#names + 1] = k end
    table.sort(names)
    return n, wrong_item, table.concat(names, ',')
end

local function count_items(tname)
    local t = df.item_type[tname]
    local n = 0
    for _, i in ipairs(w.items.all) do
        if i:getType() == t then n = n + 1 end
    end
    return n
end

-- Indexing a DFHack vector past its end raises rather than returning nil, and an order
-- that finished is erased, so every read of "the order we just placed" has to be guarded.
local function first_order()
    if #w.manager_orders.all > 0 then return w.manager_orders.all[0] end
    return nil
end

local function free_of(tname)
    local t = df.item_type[tname]
    local n = 0
    for _, i in ipairs(w.items.all) do
        if i:getType() == t and not (i.flags.in_job or i.flags.forbid
            or i.flags.dump or i.flags.removed) then
            local holder
            pcall(function() holder = dfhack.items.getHolderBuilding(i) end)
            if not holder or holder:getType() == df.building_type.Wagon then n = n + 1 end
        end
    end
    return n
end

-- Make sure the fort has material to work with, so a "no jobs issued" result means the
-- tool refused rather than the fort being empty.
local function ensure_stock(tname, want)
    local proto
    for _, i in ipairs(w.items.all) do
        if i:getType() == df.item_type[tname] then proto = i; break end
    end
    if not proto then return free_of(tname) end
    local u = dfhack.units.getCitizens(true)[1]
    while free_of(tname) < want do
        local r = dfhack.items.createItem(u, df.item_type[tname], -1,
            proto:getMaterial(), proto:getMaterialIndex())
        local it = type(r) == 'table' and r[1] or r
        if not it then break end
        it.flags.forbid = false
        dfhack.items.moveToGround(it, xyz2pos(u.pos.x, u.pos.y, u.pos.z))
    end
    return free_of(tname)
end

local function set_forbid(tname, on)
    local n = 0
    for _, i in ipairs(w.items.all) do
        if i:getType() == df.item_type[tname] and not i.flags.in_job then
            i.flags.forbid = on; n = n + 1
        end
    end
    return n
end

local function reset()
    for _, e in ipairs(manager_jobs()) do
        pcall(function() dfhack.job.removeJob(e.job) end)
    end
    local mo = w.manager_orders
    while #mo.all > 0 do mo.all:erase(#mo.all - 1) end
    _G.BONSAI_STANDING = {}
    _G.BONSAI_ORDERS = {}
end

-- What the agent has asked for and not yet been given. The DF order is only the current
-- batch, so this ledger is what "amount left" means to the caller.
local function owed(jname)
    for _, e in ipairs(_G.BONSAI_ORDERS or {}) do
        if e.job == jname then return e.remaining end
    end
    return 0
end

-- ---------------------------------------------------------------- preconditions
local shops = workshops()
local kinds = {}
for _, b in ipairs(shops) do kinds[#kinds + 1] = df.workshop_type[b.type] end
table.sort(kinds)
print(string.format('-- fort: %d workshops [%s], %d citizens',
    #shops, table.concat(kinds, ','), #dfhack.units.getCitizens(true)))
if #shops == 0 then print('ABORT: no workshop; build one first'); return end

reset()
local logs = ensure_stock('WOOD', 12)
local rocks = ensure_stock('BOULDER', 6)
print(string.format('-- stock: %d free logs, %d free boulders', logs, rocks))

-- ================================================================ 1. bad input
local before_orders = #w.manager_orders.all
local before_jobs = #manager_jobs()
apply('add_workorder\tNoSuchJobType\t5')
ok('unknown job creates nothing',
    #w.manager_orders.all == before_orders and #manager_jobs() == before_jobs,
    string.format('orders %d->%d jobs %d->%d', before_orders,
        #w.manager_orders.all, before_jobs, #manager_jobs()))
reset()

-- ================================================================ 2. order fields
-- Ask for more than one workshop can hold so the order survives to be inspected.
apply('add_workorder\tConstructBed\t12')
local o = first_order()
ok('a batch order exists', o ~= nil, o and ('id=' .. o.id) or 'no order')
if o then
    local issued, wrong, used = jobs_for(o.id, 'WOOD')
    -- The DF order describes exactly the jobs queued for it, because DF retires an order
    -- as soon as those jobs are done regardless of what amount_left says. The rest of
    -- the request waits in our ledger.
    ok('order matches the jobs queued for it',
        o.amount_total == issued and o.amount_left == issued,
        string.format('issued=%d left=%d total=%d', issued, o.amount_left, o.amount_total))
    ok('the remainder is still owed', issued + owed('ConstructBed') == 12,
        string.format('issued=%d owed=%d', issued, owed('ConstructBed')))
    ok('order marked validated+active',
        o.status.validated and o.status.active,
        string.format('val=%s act=%s', tostring(o.status.validated),
            tostring(o.status.active)))
    ok('every job carries by_manager + order_id', issued > 0,
        'jobs=' .. issued)
    ok('bed jobs took wood, not stone', wrong == 0, 'non-wood reagents=' .. wrong)
    ok('bed order went to a Carpenters shop', used == 'Carpenters', 'shops=' .. used)
    ok('batch respects workshop capacity', issued <= 5, 'issued=' .. issued)
end

-- A second dispatch must top the queue back up to the workshop's capacity and no
-- further: over-issuing here is how an order for twelve becomes twenty jobs.
apply('advance	1')
local total_q = #manager_jobs()
ok('second dispatch does not over-issue', total_q <= 5,
    string.format('queued=%d owed=%d', total_q, owed('ConstructBed')))
ok('nothing is lost between dispatches', total_q + owed('ConstructBed') == 12,
    string.format('queued=%d owed=%d', total_q, owed('ConstructBed')))
reset()

-- ================================================================ 3. no material
-- With every log forbidden a bed order must issue nothing AND must not consume the
-- count: a decremented amount_left with no job is work the agent silently never gets.
set_forbid('WOOD', true)
apply('add_workorder\tConstructBed\t4')
local o2 = first_order()
if o2 then
    local issued2 = jobs_for(o2.id, 'WOOD')
    ok('no wood -> no jobs', issued2 == 0, 'jobs=' .. issued2)
    ok('no wood -> count intact', owed('ConstructBed') == 4,
        'owed=' .. owed('ConstructBed'))
    ok('no wood -> no stone substituted for a bed',
        select(2, jobs_for(o2.id, 'WOOD')) == 0,
        'non-wood reagents=' .. select(2, jobs_for(o2.id, 'WOOD')))
else
    ok('no wood -> no jobs', #manager_jobs() == 0, 'no batch order was created')
    ok('no wood -> count intact', owed('ConstructBed') == 4,
        'owed=' .. owed('ConstructBed'))
end
set_forbid('WOOD', false)
reset()

-- ================================================================ 4. workshop match
-- BrewDrink has no workshop-and-reagent rule, so it must be refused outright rather
-- than queued at whatever workshop happens to exist.
apply('add_workorder	BrewDrink	3')
ok('unsupported job refused outright',
    #w.manager_orders.all == 0 and #manager_jobs() == 0,
    string.format('orders=%d jobs=%d', #w.manager_orders.all, #manager_jobs()))
reset()

-- MakeCrafts is supported but needs a Craftsdwarfs shop. Without one the order stands
-- and waits; it must not be handed to the carpenter.
local has_craft = false
for _, b in ipairs(workshops()) do
    if b.type == df.workshop_type.Craftsdwarfs then has_craft = true end
end
if has_craft then
    print('SKIP  no-craftshop case                 (this fort has a Craftsdwarfs)')
else
    apply('add_workorder	MakeCrafts	3')
    local o4 = first_order()
    local issued4 = o4 and jobs_for(o4.id) or 0
    ok('craft order not given to a carpenter', issued4 == 0, 'jobs=' .. issued4)
    ok('craft order kept its full count', owed('MakeCrafts') == 3,
        'owed=' .. owed('MakeCrafts'))
    reset()
end

-- With the right shop present, a stone job must take stone, not a log.
apply('build_workshop	Craftsdwarfs')
local built_craft = false
for _, b in ipairs(workshops()) do
    if b.type == df.workshop_type.Craftsdwarfs then
        built_craft = true
        -- test fixture: a freshly placed workshop sits at stage 0 until a dwarf builds
        -- it, and this battery does not advance time. Finish it outright so the case
        -- under test is the reagent choice, not the construction queue.
        pcall(function() b:setBuildStage(b:getMaxBuildStage()) end)
        pcall(function() b.flags.exists = true end)
        for i = #b.jobs - 1, 0, -1 do
            pcall(function() dfhack.job.removeJob(b.jobs[i]) end)
        end
    end
end
if not built_craft then
    print('SKIP  stone-reagent case                (Craftsdwarfs shop did not build)')
else
    -- ask for more than one shop can hold, or the order finishes and is retired before
    -- it can be inspected - which made this case pass vacuously with zero jobs
    apply('add_workorder	MakeCrafts	8')
    local o5 = first_order()
    local issued5, wrong5, used5 = 0, 0, ''
    if o5 then issued5, wrong5, used5 = jobs_for(o5.id, 'BOULDER') end
    ok('craft order actually issued jobs', issued5 > 0,
        'jobs=' .. issued5 .. ' owed=' .. owed('MakeCrafts'))
    ok('craft order went to Craftsdwarfs', used5 == 'Craftsdwarfs', 'shops=' .. used5)
    ok('craft jobs took stone, not wood', issued5 > 0 and wrong5 == 0,
        'non-stone reagents=' .. wrong5)
    reset()
end

-- ================================================================ 5. conditions
apply('add_workorder_conditional	ConstructBed	2	BED	3')
local standing = #(_G.BONSAI_STANDING or {})
ok('standing order registered', standing == 1, 'registered=' .. standing)

-- below <= 0 is meaningless and must be refused rather than looping for ever
apply('add_workorder_conditional	ConstructBed	2	BED	0')
ok('threshold of zero refused', #(_G.BONSAI_STANDING or {}) == 1,
    'registered=' .. #(_G.BONSAI_STANDING or {}))

apply('add_workorder_conditional	ConstructBed	2	NOSUCHITEM	5')
ok('unknown item refused', #(_G.BONSAI_STANDING or {}) == 1,
    'registered=' .. #(_G.BONSAI_STANDING or {}))

apply('add_workorder_conditional	ConstructBed	2	BED	3')
ok('duplicate standing order not doubled', #(_G.BONSAI_STANDING or {}) == 1,
    'registered=' .. #(_G.BONSAI_STANDING or {}))

-- stock is above the threshold, so the guard must stay quiet
reset()
local beds_now = count_items('BED')
apply('add_workorder_conditional	ConstructBed	3	BED	1')
ok('guard silent when stock is above it', #manager_jobs() == 0,
    string.format('beds=%d threshold=1 jobs=%d', beds_now, #manager_jobs()))

-- now put the threshold above stock: it must fire on the spot
reset()
apply('add_workorder_conditional	ConstructBed	3	BED	' .. (beds_now + 4))
local fired = #manager_jobs()
ok('guard fires when stock is below it', fired > 0,
    string.format('beds=%d threshold=%d jobs=%d', beds_now, beds_now + 4, fired))
ok('guard orders the shortfall, not more', fired <= 3, 'jobs=' .. fired)

-- a second dispatch with the same low stock must NOT queue the batch again: the first
-- batch is still in flight and re-ordering it every round buries the workshop
apply('advance	1')
local fired2 = #manager_jobs()
ok('in-flight work is not re-ordered', fired2 == fired,
    string.format('jobs %d -> %d', fired, fired2))
reset()

-- ================================================================ 6. id hygiene
local next_before = w.manager_orders.manager_order_next_id
apply('add_workorder\tConstructTable\t2', 'add_workorder\tConstructDoor\t2')
local ids, dup = {}, false
for _, x in ipairs(w.manager_orders.all) do
    if ids[x.id] then dup = true end
    ids[x.id] = true
end
ok('order ids unique', not dup)
ok('next_id advanced', w.manager_orders.manager_order_next_id > next_before,
    string.format('%d -> %d', next_before, w.manager_orders.manager_order_next_id))
reset()

print(string.format('-- ORDERCHECK pass=%d fail=%d', pass, fail))
