-- bonsai-apply-actions: deterministic evaluator-side dispatch of the agent's action
-- intents (anti-forgery). Reads agent_actions.txt (tab-separated: verb\targ1\targ2),
-- applies ONLY the allow-listed verbs, never executes agent code. Reports counts.
-- Kept in sync with game_scorer.ALLOWED_VERBS.
-- the actions file is named per episode; parallel forts must not read each
-- other's intents
local path = (...) or "/srv/df-bonsai/current/agent_actions.txt"
local f = io.open(path, "r")
if not f then print("APPLY no-actions"); return end
local w = df.global.world
local cits = dfhack.units.getCitizens(true)
local u1 = cits[1]
local c = { set_labor = 0, designate_dig = 0, create_stockpile = 0, add_workorder = 0,
            build_workshop = 0, advance = 0, assign_noble = 0,
            add_workorder_conditional = 0 }

-- Standing orders, kept evaluator-side, because DF's own manager orders do not work on
-- this save. Measured: an order placed through DFHack's shipped `workorder` validates in
-- ~8,000 ticks on a real 136-dwarf fort, and never validates here across 30,000 ticks —
-- with the manager seated and confirmed by getNoblePositions, an office built with real
-- extents and owned via setOwner, the manager standing inside it, and
-- plotinfo.nobles.manager_cooldown counting down. Why that subsystem is inert on this
-- fort is unresolved.
--
-- What the agent actually needs is the CAPABILITY, not the subsystem: "keep at least N of
-- X in stock". That is expressible over the direct workshop-job path, which does work and
-- does produce items. Each dispatch re-checks the stock level and tops it up, which is
-- what a repeating manager order would have done anyway.
_G.BONSAI_STANDING = _G.BONSAI_STANDING or {}

-- Seat a citizen in a fort position so THE GAME believes it, not just the nobles screen.
--
-- Writing entity_position_assignment.histfig is the obvious move and it is a silent
-- no-op: measured live, the screen field went -1 -> 1741 and dfhack.units.getNoblePositions
-- still returned nothing, because DF and DFHack both answer "who holds this office?" by
-- walking the HISTFIG's entity_links for a histfig_entity_link_positionst and binsearching
-- assignments by the link's assignment_id. Same failure shape as the dig designations that
-- wrote cleanly and generated zero jobs.
--
-- MANAGER, BOOKKEEPER, BROKER and the rest are SITE positions living on the fortress
-- entity. make-monarch.lua uses the CIV entity because MONARCH is a civ position; copying
-- it verbatim seats nobody.
local function assign_noble(code, unit)
    local ent = df.global.plotinfo.main.fortress_entity
    if not (ent and unit) then return false end
    local hf = df.historical_figure.find(unit.hist_figure_id)
    if not hf then return false end                 -- some units have no histfig at all
    local pos, idx, asg
    for _, p in ipairs(ent.positions.own) do
        if p.code == code then pos = p; break end
    end
    if not pos then return false end
    for i, a in ipairs(ent.positions.assignments) do
        if a.position_id == pos.id and (a.histfig == -1 or a.histfig == hf.id) then
            asg, idx = a, i; break
        end
    end
    if not asg then return false end                -- office already taken

    -- Strip the POSITION link a PREVIOUS holder still carries for this assignment.
    -- DF's own lookup walks histfig links rather than the assignment, so a stale link
    -- leaves two figures claiming one seat.
    if asg.histfig ~= -1 and asg.histfig ~= hf.id then
        local old = df.historical_figure.find(asg.histfig)
        if old then
            for i = #old.entity_links - 1, 0, -1 do
                local l = old.entity_links[i]
                if df.histfig_entity_link_positionst:is_instance(l)
                    and l.entity_id == ent.id and l.assignment_id == asg.id then
                    old.entity_links:erase(i)
                end
            end
        end
    end

    -- histfig2 is the half DF fills in and we did not. Measured on a hand-played fort:
    -- seating with histfig alone left plotinfo.nobles.manager_cooldown pinned at 0
    -- forever (DF never finds the officeholder, so orders are never validated); every
    -- position DF had appointed itself carried histfig2 == histfig. never_cull is the
    -- other bit DF stamps on a seated noble.
    asg.histfig = hf.id
    asg.histfig2 = hf.id
    hf.flags.never_cull = true

    for _, v in ipairs(hf.entity_links) do          -- idempotent: never link twice
        if df.histfig_entity_link_positionst:is_instance(v)
           and v.entity_id == ent.id and v.assignment_id == asg.id then return true end
    end
    hf.entity_links:insert('#', {
        new = df.histfig_entity_link_positionst,
        entity_id = ent.id, assignment_id = asg.id,
        assignment_vector_idx = idx, link_strength = 100,
        start_year = df.global.cur_year })
    return true
end

-- A dwarf in a military squad is refused the office by DF. Measured: seating the
-- squad member our "best by skill" picker chose left the manager cooldown dead, and
-- seating a squad-free citizen on the same fort woke it within 70 ticks.
local function in_squad(unit)
    local hf = df.historical_figure.find(unit.hist_figure_id)
    if not hf then return false end
    for _, l in ipairs(hf.entity_links) do
        if df.histfig_entity_link_squadst:is_instance(l) then return true end
    end
    return (unit.military and unit.military.squad_id or -1) ~= -1
end

-- A free building material, or nil. Workshops need one and DFHack will NOT find it for
-- you: constructBuilding with no `items` produces a building whose ConstructBuilding job
-- has no reagent, DF cancels the job and drops the building, and the caller sees a
-- perfectly successful return value. Measured live: build_workshop reported success,
-- world.buildings.all held nothing but the wagon 20,000 ticks later, and the identical
-- call WITH a log attached built the workshop. That silent failure is why the fort never
-- had a workshop, and therefore why no manager order could ever be worked.
local function free_material(prefer_stone)
    local first, second = df.item_type.WOOD, df.item_type.BOULDER
    if prefer_stone then first, second = second, first end
    for _, want in ipairs({first, second}) do
        for _, it in ipairs(w.items.all) do
            if it:getType() == want
               and not (it.flags.in_job or it.flags.forbid or it.flags.dump
                        or it.flags.construction or it.flags.removed) then
                -- A workshop is MADE of its log, and handing that same log to a job
                -- destroys the workshop — observed live, shops went 1 to 0 the moment a
                -- bed job claimed a reagent. But `in_building` alone is far too broad:
                -- at embark every supply sits inside the WAGON, which is also a
                -- building, so excluding it left the fort unable to build anything.
                -- Ask who holds the item instead.
                local holder = nil
                pcall(function() holder = dfhack.items.getHolderBuilding(it) end)
                if not holder or holder:getType() == df.building_type.Wagon then
                    return it
                end
            end
        end
    end
    return nil
end

-- Queue N jobs of one type directly on a finished workshop. Returns how many took.
--
-- Shared by add_workorder and add_workorder_conditional so the two cannot drift: the
-- conditional verb is exactly this, re-evaluated against a stock level on every dispatch.
local function issue_jobs(jname, n)
    local shop
    for _, b in ipairs(w.buildings.all) do
        if b:getType() == df.building_type.Workshop and b.construction_stage >= 3 then
            shop = b; break
        end
    end
    if not shop or df.job_type[jname] == nil then return 0 end
    local made = 0
    for _ = 1, math.min(n, 20) do
        -- One reagent per job, claimed up front. Anything DFHack creates without one is
        -- cancelled by DF within a few thousand ticks and silently removed — the same
        -- trap that made build_workshop a no-op for a whole game year.
        local item = free_material(false)
        if not item then break end
        local job = df.job:new()
        job.job_type = df.job_type[jname]
        job.pos = xyz2pos(shop.centerx, shop.centery, shop.z)
        pcall(function() job.material_category.wood = true end)
        dfhack.job.addGeneralRef(job, df.general_ref_type.BUILDING_HOLDER, shop.id)
        shop.jobs:insert('#', job)
        dfhack.job.linkIntoWorld(job, true)
        local ok = pcall(function()
            dfhack.job.attachJobItem(job, item, df.job_role_type.Reagent, 0, -1)
        end)
        if ok and #job.items > 0 then made = made + 1 end
    end
    return made
end

-- ---------------------------------------------------------------- work orders
-- DF's own work-order machinery does not run on our forts, and it is not our seating
-- that stops it: measured side by side against a hand-played 119-dwarf fort on the same
-- binary, `plotinfo.nobles.manager_cooldown` decrements at the normal 1-per-10-ticks and
-- then fails its check at 0, so no ManageWorkOrders job is ever scheduled, nothing is
-- validated, and even an order forced to validated+active with a built workshop and
-- twenty free logs produces no job. Population, office, world age, squad membership,
-- order shape and the embark procedure are all eliminated (tools/df_docs/workorder_contract.md).
--
-- So the evaluator plays manager. The order is a REAL df.manager_order living in
-- world.manager_orders, so it is visible and countable exactly like a player's; we
-- perform the dispatch step DF refuses to, emitting the same job shape DF emits on the
-- working fort: flags.by_manager set, order_id pointing back at the order, a building
-- holder, and a reagent attached.

local WORKSHOP_FOR = {
    ConstructBed = df.workshop_type.Carpenters,
    ConstructTable = df.workshop_type.Carpenters,
    ConstructThrone = df.workshop_type.Carpenters,
    ConstructDoor = df.workshop_type.Carpenters,
    ConstructCabinet = df.workshop_type.Carpenters,
    ConstructBin = df.workshop_type.Carpenters,
    ConstructBarrel = df.workshop_type.Carpenters,
    MakeCrafts = df.workshop_type.Craftsdwarfs,
    BrewDrink = df.workshop_type.Still,
    PrepareMeal = df.workshop_type.Kitchen,
}

local function shop_for(job_type)
    local want = WORKSHOP_FOR[df.job_type[job_type]]
    local fallback
    for _, b in ipairs(w.buildings.all) do
        if b:getType() == df.building_type.Workshop and b.construction_stage >= 3 then
            if want and b.type == want then return b end
            fallback = fallback or b
        end
    end
    return want and nil or fallback        -- never hand a bed order to a smelter
end

-- Create the order the agent asked for, as a real manager order.
local function create_order(jname, amount)
    if df.job_type[jname] == nil then return nil end
    local mo = w.manager_orders
    local o = df.manager_order:new()
    o.id = mo.manager_order_next_id
    mo.manager_order_next_id = mo.manager_order_next_id + 1
    o.job_type = df.job_type[jname]
    o.amount_left = amount
    o.amount_total = amount
    o.frequency = 0                        -- OneTime
    o.max_workshops = 0                    -- 0 is unlimited
    o.workshop_id = -1
    -- An order with no material class never dispatches, even on a fort where the
    -- manager works: measured, the same order gained a reagent the moment
    -- material_category.wood was set and completed within 10,000 ticks.
    pcall(function() o.material_category.wood = true end)
    mo.all:insert('#', o)
    return o
end

local function dispatch_orders()
    local made = 0
    local mo = w.manager_orders
    for i = #mo.all - 1, 0, -1 do
        local o = mo.all[i]
        if o.amount_left > 0 then
            o.status.validated = true      -- we are the manager; say so out loud
            o.status.active = true
            local shop = shop_for(o.job_type)
            if shop then
                local cap = 5
                pcall(function() cap = shop.profile.max_general_orders end)
                local room = math.max(0, cap - #shop.jobs)
                for _ = 1, math.min(o.amount_left, room, 10) do
                    local item = free_material(false)
                    if not item then break end
                    local job = df.job:new()
                    job.job_type = o.job_type
                    job.pos = xyz2pos(shop.centerx, shop.centery, shop.z)
                    job.flags.by_manager = true
                    job.order_id = o.id
                    pcall(function() job.material_category.wood = true end)
                    dfhack.job.addGeneralRef(job, df.general_ref_type.BUILDING_HOLDER, shop.id)
                    shop.jobs:insert('#', job)
                    dfhack.job.linkIntoWorld(job, true)
                    local ok = pcall(function()
                        dfhack.job.attachJobItem(job, item, df.job_role_type.Reagent, 0, -1)
                    end)
                    if ok and #job.items > 0 then
                        made = made + 1
                        o.amount_left = o.amount_left - 1
                    else
                        -- a job with no reagent is cancelled by DF and silently removed,
                        -- so drop it here rather than counting a phantom
                        pcall(function() dfhack.job.removeJob(job) end)
                        break
                    end
                end
            end
            if o.amount_left <= 0 and o.frequency == 0 then
                -- DF retires a finished one-time order. Erase only: calling o:delete()
                -- as well left the vector reporting zero orders while an unfinished one
                -- was still in it, i.e. the container owns these and freeing them twice
                -- corrupts it. A retired order struct is a few dozen bytes; a corrupted
                -- order list loses the agent's work silently.
                mo.all:erase(i)
            end
        end
    end
    return made
end

-- How many of an item type the fort holds, ignoring what is already spoken for.
local function stock_of(item_name)
    local t = df.item_type[item_name]
    if t == nil then return nil end
    local n = 0
    for _, it in ipairs(w.items.all) do
        if it:getType() == t and not (it.flags.in_job or it.flags.forbid
                                      or it.flags.removed) then n = n + 1 end
    end
    return n
end

-- Re-run every standing order the agent has placed. This is what a repeating manager
-- order would have done; it runs on each dispatch instead of on DF's manager cycle.
local function run_standing()
    local fired = 0
    for _, s in ipairs(_G.BONSAI_STANDING) do
        local have = stock_of(s.item)
        if have ~= nil and have < s.below then
            fired = fired + issue_jobs(s.job, math.min(s.batch, s.below - have))
        end
    end
    return fired
end

-- Which citizen gets the job when the agent says "best".
--
-- A real fitness score over skills, attributes and stress is still to come; until it
-- exists this is deliberately the dumbest defensible rule — most total skill experience,
-- ties broken by unit id so it is reproducible across runs. Honest placeholder rather
-- than a weighted formula nobody has validated.
local function pick_best(cits)
    local best, bestscore = nil, -1
    for _, u in ipairs(cits) do
        local s = 0
        pcall(function()
            for _, sk in ipairs(u.status.current_soul.skills) do s = s + sk.rating end
        end)
        if s > bestscore or (s == bestscore and best and u.id < best.id) then
            best, bestscore = u, s
        end
    end
    return best or cits[1]
end

local function split(line)
    local t = {}
    for tok in string.gmatch(line, "[^\t]+") do t[#t + 1] = tok end
    return t
end

-- Placement cursor, persisted in a Lua global for the whole episode (globals survive
-- between dfhack-run calls). Without it every create_stockpile call recomputed the same
-- spots relative to the first citizen, so only the FIRST round ever placed anything and
-- the development term could be earned exactly once per episode.
_G.BONSAI_PLACE = _G.BONSAI_PLACE or { stock = 0, shop = 0, dig = nil }
local P = _G.BONSAI_PLACE

-- A ring of candidate build sites around the wagon, walked outwards. Keeps successive
-- placements on fresh ground instead of colliding with what is already there.
local function site(n, radius)
    if not u1 then return nil end
    local ring = radius + math.floor(n / 8) * 3
    local a = (n % 8) * (math.pi / 4)
    return math.floor(u1.pos.x + ring * math.cos(a)),
           math.floor(u1.pos.y + ring * math.sin(a)),
           u1.pos.z
end

for line in f:lines() do
    local a = split(line)
    local verb = a[1]
    if verb == "set_labor" then
        pcall(function()
            local lid = df.unit_labor[a[2]]
            if lid then
                local on = (a[3] ~= "False" and a[3] ~= "false" and a[3] ~= "0")
                for _, u in ipairs(cits) do u.status.labors[lid] = on end
                c.set_labor = c.set_labor + 1
            end
        end)
    elseif verb == "designate_dig" then
        -- Digging in DF needs REACHABILITY. The old dispatch stamped dig flags on a
        -- 5x5x13 block straight down from a dwarf standing on the surface: the top layer
        -- is open air (a dig flag there is a no-op) and everything below is sealed rock
        -- nobody can walk to, so a live 10-fort-day episode excavated exactly zero tiles
        -- however many tiles were "designated".
        --
        -- So designate what a player would: a staircase down from the dwarf, then a room
        -- carved off each landing. Every tile is connected to the one above it.
        pcall(function()
            local n = tonumber(a[2]) or 25
            if not u1 then return end
            -- Pin the shaft head for the whole episode. Citizen[1] WANDERS, so using
            -- its live position started a fresh one-tile shaft at a new spot on every
            -- call (observed: 96,91 then 95,98) - orphaned designations that connect
            -- to nothing and can never be reached, hence zero tiles actually dug.
            P.dig = P.dig or { u1.pos.x, u1.pos.y, u1.pos.z }
            local ox, oy, oz = P.dig[1], P.dig[2], P.dig[3]
            local placed = 0
            local DIG = df.tile_dig_designation
            local function mark(x, y, z, kind)
                if placed >= n then return end
                pcall(function()
                    local des = dfhack.maps.getTileFlags(x, y, z)
                    if not des then return end
                    local tt = dfhack.maps.getTileType(x, y, z)
                    local sh = tt and df.tiletype.attrs[tt].shape
                    -- only solid rock is diggable; flagging air or an existing floor
                    -- silently achieves nothing
                    if kind == DIG.Default and sh ~= df.tiletype_shape.WALL then return end
                    des.dig = kind
                    -- Setting the tile flag is NOT enough. DF only rescans blocks that
                    -- are flagged as carrying new designations, so writing designations
                    -- through DFHack without this produced a perfectly valid staircase
                    -- that generated ZERO dig jobs: measured 11 tiles marked, 0 jobs,
                    -- 0 rock removed over 3000 ticks, while `dig-now` on the same
                    -- designations excavated 35 tiles immediately.
                    local blk = dfhack.maps.getTileBlock(x, y, z)
                    if blk then blk.flags.designated = true end
                    placed = placed + 1
                end)
            end
            -- shaft: down-stair at the surface, up/down stairs beneath it
            mark(ox, oy, oz, DIG.DownStair)
            local depth = 0
            for dz = 1, 10 do
                mark(ox, oy, oz - dz, DIG.UpDownStair)
                depth = dz
                if placed >= n then break end
            end
            -- rooms off each landing, spiralling out so successive calls extend the fort
            -- rather than re-designating the same tiles
            P.digring = (P.digring or 0)
            for dz = 1, depth do
                for r = 1 + P.digring, 3 + P.digring do
                    for _, d in ipairs({ { r, 0 }, { -r, 0 }, { 0, r }, { 0, -r } }) do
                        mark(ox + d[1], oy + d[2], oz - dz, DIG.Default)
                        if placed >= n then break end
                    end
                    if placed >= n then break end
                end
                if placed >= n then break end
            end
            if placed > 0 then
                P.digring = P.digring + 1
                -- ask the engine to run its dig-job scan on the next tick
                pcall(function() df.global.process_dig = true end)
                pcall(function() df.global.process_jobs = true end)
            end
            c.designate_dig = c.designate_dig + placed
        end)
    elseif verb == "create_stockpile" then
        pcall(function()
            local n = tonumber(a[2]) or 1
            for _ = 1, n do
                local x, y, z = site(P.stock, 4)
                if x then
                    local ok = pcall(function()
                        local b = dfhack.buildings.constructBuilding{
                            type = df.building_type.Stockpile, abstract = true,
                            pos = { x = x, y = y, z = z }, width = 2, height = 2 }
                        if b then c.create_stockpile = c.create_stockpile + 1 end
                    end)
                    P.stock = P.stock + 1
                    if not ok then break end
                end
            end
        end)
    elseif verb == "build_workshop" then
        -- Without a workshop no manager order can ever be worked, so `workorders_done`
        -- was structurally pinned at 0 and half the development weight was unearnable.
        pcall(function()
            local name = a[2] or "Carpenters"
            local sub = df.workshop_type[name]
            if sub == nil then sub = df.workshop_type.Carpenters end
            -- Masons and Craftsdwarfs work stone; the rest of what an early fort builds
            -- wants wood. Either falls back to the other if the fort has none.
            local item = free_material(name == "Masons" or name == "Craftsdwarfs")
            if not item then return end          -- nothing to build it out of, so do not
                                                 -- claim we did
            local x, y, z = site(P.shop, 8)
            if x then
                local b = dfhack.buildings.constructBuilding{
                    type = df.building_type.Workshop, subtype = sub,
                    pos = { x = x, y = y, z = z }, items = { item } }
                -- Count it only if DF actually attached a build job with a reagent.
                -- The old count was "constructBuilding returned something", which it
                -- does even when the building is about to be cancelled and removed.
                if b and #b.jobs > 0 and #b.jobs[0].items > 0 then
                    c.build_workshop = c.build_workshop + 1
                end
                P.shop = P.shop + 1
            end
        end)
    elseif verb == "assign_noble" then
        pcall(function()
            local code = a[2]
            if not code or #code == 0 then return end
            local who = a[3]
            local u = nil
            if who and who ~= "best" and who ~= "" then
                for _, x in ipairs(cits) do
                    if tostring(x.id) == who then u = x end
                end
            end
            if not u then
                -- DF refuses an officeholder who is in a squad, so exclude them before
                -- ranking rather than discovering it as a silently dead noble later.
                local free = {}
                for _, x in ipairs(cits) do
                    if not in_squad(x) then free[#free + 1] = x end
                end
                u = pick_best(#free > 0 and free or cits)
            end
            if u and assign_noble(code, u) then
                c.assign_noble = c.assign_noble + 1
            end
        end)
    elseif verb == "add_workorder" then
        -- A manager order is NOT how the guide makes its first beds. At 17:10 it clicks
        -- the carpenter and adds a task straight to the workshop -- no manager, no
        -- validation, no office. That distinction decides whether anything gets made:
        -- manager orders never validate on this save (30,000 ticks, manager seated and
        -- confirmed, office built and owned, manager standing inside it), while a direct
        -- workshop job produces a bed inside 4,000.
        pcall(function()
            local amount = tonumber(a[3]) or tonumber(a[2]) or 10
            local jname = (a[2] and df.job_type[a[2]] ~= nil) and a[2] or "ConstructBed"
            -- A real manager order now, plus the dispatch DF will not do for us. The
            -- order shows up in world.manager_orders like a player's and its amount_left
            -- counts down as the jobs are issued.
            if create_order(jname, amount) then
                c.add_workorder = c.add_workorder + dispatch_orders()
            else
                c.add_workorder = c.add_workorder + issue_jobs(jname, amount)
            end
        end)
    elseif verb == "add_workorder_conditional" then
        -- "Keep at least N of X" -- the standing order a player actually writes, e.g.
        -- never fewer than five empty barrels. Registered once here, then re-evaluated
        -- on every dispatch by run_standing().
        pcall(function()
            local jname = (a[2] and df.job_type[a[2]] ~= nil) and a[2] or "ConstructBed"
            local batch = tonumber(a[3]) or 10
            local item  = a[4]
            local below = tonumber(a[5]) or 0
            if not item or df.item_type[item] == nil or below <= 0 then return end
            for _, s2 in ipairs(_G.BONSAI_STANDING) do
                if s2.job == jname and s2.item == item then
                    s2.batch, s2.below = batch, below      -- re-stating one updates it
                    c.add_workorder_conditional = c.add_workorder_conditional + 1
                    return
                end
            end
            table.insert(_G.BONSAI_STANDING,
                         { job = jname, batch = batch, item = item, below = below })
            c.add_workorder_conditional = c.add_workorder_conditional + 1
        end)
    end
end
f:close()

-- Top up anything the agent asked to be kept in stock. A repeating manager
-- order would have done this on DF's schedule; we do it on the dispatch schedule.
local topped = run_standing()
if topped > 0 then c.add_workorder = c.add_workorder + topped end

-- Carry every outstanding work order forward. DF's manager never runs on our forts, so
-- an order left with amount_left > 0 would sit there for ever; this is the second and
-- every later visit the manager would have paid it.
local dispatched = dispatch_orders()
if dispatched > 0 then c.add_workorder = c.add_workorder + dispatched end

local rep = {}
for k, v in pairs(c) do rep[#rep + 1] = k .. "=" .. v end
table.sort(rep)
print("APPLY " .. table.concat(rep, " "))
