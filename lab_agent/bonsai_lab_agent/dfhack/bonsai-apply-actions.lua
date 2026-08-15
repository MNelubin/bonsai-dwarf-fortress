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

-- Can the fort actually get to it? Every verb below that places something, claims
-- something or digs something asks this first. Loaded defensively because a missing
-- module must not take the whole dispatch down with it.
local reach
pcall(function() reach = reqscript('bonsai-reach') end)
local REACH_GROUPS = reach and reach.fort_groups() or nil
local c = { set_labor = 0, designate_dig = 0, create_stockpile = 0, add_workorder = 0,
            build_workshop = 0, advance = 0, assign_noble = 0,
            add_workorder_conditional = 0, build_farm_plot = 0, set_crop = 0,
            set_kitchen_flag = 0, create_zone = 0, assign_room = 0,
            place_furniture = 0, set_dwarf_labor = 0, cancel_dwarf_job = 0,
            configure_stockpile = 0, chop_trees = 0, smooth = 0,
            build_construction = 0, set_standing_order = 0,
            set_dig_priority = 0, apply_template = 0 }

-- Work orders live in _G.BONSAI_ORDERS (declared with the order code below) and survive
-- between dispatches within one DF process. They are re-checked on every dispatch, which
-- is the visit DF's own manager pays on a normal fort and never pays here.
_G.BONSAI_STANDING = nil                    -- superseded by the order ledger

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

-- A free item of the requested type, or nil. Workshops and jobs need one and DFHack will
-- NOT find it for you: constructBuilding with no `items` produces a building whose
-- ConstructBuilding job has no reagent, DF cancels the job and drops the building, and
-- the caller sees a perfectly successful return value. Measured live: build_workshop
-- reported success, world.buildings.all held nothing but the wagon 20,000 ticks later,
-- and the identical call WITH a log attached built the workshop.
--
-- `wants` is a list of acceptable df.item_type values in order of preference. It used to
-- be a prefer_stone boolean that always allowed both wood and stone, which meant a bed
-- job could be handed a boulder once the logs ran out — DF cancels that job and the
-- order's amount_left has already been spent on it.
local function free_material(...)
    local wants = { ... }
    if #wants == 0 then wants = { df.item_type.WOOD, df.item_type.BOULDER } end
    for _, want in ipairs(wants) do
        for _, it in ipairs(w.items.all) do
            if it:getType() == want then
                -- One question instead of six flags. bonsai-reach checks claimability
                -- AND that somebody can walk to it, which the flag list never did: on
                -- this fort 14 of 15 barrels and 30 of 144 seed stacks belong to another
                -- civilisation and are as unavailable as if they were behind a wall.
                local usable = false
                if reach then
                    usable = reach.item(it, REACH_GROUPS)
                else
                    usable = not (it.flags.in_job or it.flags.forbid or it.flags.dump
                                  or it.flags.construction or it.flags.removed
                                  or it.flags.foreign)
                end
                if usable then
                    -- A workshop is MADE of its log, and handing that same log to a job
                    -- destroys the workshop — observed live, shops went 1 to 0 the moment
                    -- a bed job claimed a reagent. But `in_building` alone is far too
                    -- broad: at embark every supply sits inside the WAGON, which is also
                    -- a building, so excluding it left the fort unable to build anything.
                    -- Ask who holds the item instead.
                    local holder = nil
                    pcall(function() holder = dfhack.items.getHolderBuilding(it) end)
                    if not holder or holder:getType() == df.building_type.Wagon then
                        return it
                    end
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
-- (issue_jobs used to live here: it picked the FIRST workshop of any kind and always
-- claimed a wood-or-stone reagent with material_category.wood, so a standing brew order
-- would have been queued at a carpenter with a log attached. Standing orders now go
-- through create_order/dispatch_orders like everything else, which gets them the job's
-- real workshop, its real reagent, and the same refusal on an unsupported job.)

-- ---------------------------------------------------------------- work orders
-- A work order in DF is not "make N of X". Read off a hand-played fort, the shape is
--
--     #398 MakeAsh  x5/10  Daily  val=true act=true
--          WHILE LessThan 10 of BAR (ASH)
--
-- that is: make ten, out of a named material, WHILE a stock condition holds, re-checked
-- on a schedule — and the manager is what turns it into jobs. Thirty of that fort's
-- fifty-seven orders carry a condition and every one of those is Daily.
--
-- Three things that shape looks like and this code used to get wrong:
--
--   * the amount is the FULL order (ten ash), not the shortfall. The condition is what
--     stops it: once ash reaches ten, `LessThan 10` is false and the order goes quiet.
--   * `status.active` is not "we approved it" — it is "the condition holds right now".
--     That same fort carries `#299 SmeltOre val=true act=false`, an order the manager
--     validated that is idle because there is no gold ore. Forcing active erases exactly
--     the bit that expresses the condition.
--   * the condition names a material, not just an item type: `BAR (ASH)`, not any bar.
--
-- DF's own manager never runs on our forts (see tools/df_docs/workorder_contract.md), so
-- we validate, evaluate the condition and dispatch ourselves. The order is still a real
-- df.manager_order carrying real item_conditions, so it reads in-game — and exports
-- through `orders export` — exactly like a player's.

-- Each job maps to one or more (material, workshop, reagent) variants. A job with no
-- entry is refused rather than guessed at: a job handed the wrong reagent is not a soft
-- failure, DF cancels it thousands of ticks later with the order's count already spent.
local JOB_SPEC = {
    ConstructBed     = { { mat = 'wood',  shop = 'Carpenters',   item = 'WOOD' } },
    ConstructThrone  = { { mat = 'wood',  shop = 'Carpenters',   item = 'WOOD' },
                         { mat = 'stone', shop = 'Masons',       item = 'BOULDER' } },
    ConstructTable   = { { mat = 'wood',  shop = 'Carpenters',   item = 'WOOD' },
                         { mat = 'stone', shop = 'Masons',       item = 'BOULDER' } },
    ConstructDoor    = { { mat = 'wood',  shop = 'Carpenters',   item = 'WOOD' },
                         { mat = 'stone', shop = 'Masons',       item = 'BOULDER' } },
    ConstructCabinet = { { mat = 'wood',  shop = 'Carpenters',   item = 'WOOD' },
                         { mat = 'stone', shop = 'Masons',       item = 'BOULDER' } },
    ConstructChest   = { { mat = 'wood',  shop = 'Carpenters',   item = 'WOOD' },
                         { mat = 'stone', shop = 'Masons',       item = 'BOULDER' } },
    ConstructCoffin  = { { mat = 'wood',  shop = 'Carpenters',   item = 'WOOD' },
                         { mat = 'stone', shop = 'Masons',       item = 'BOULDER' } },
    ConstructBin     = { { mat = 'wood',  shop = 'Carpenters',   item = 'WOOD' } },
    MakeBarrel       = { { mat = 'wood',  shop = 'Carpenters',   item = 'WOOD' } },
    ConstructBlocks  = { { mat = 'stone', shop = 'Masons',       item = 'BOULDER' } },
    MakeCrafts       = { { mat = 'stone', shop = 'Craftsdwarfs', item = 'BOULDER' },
                         { mat = 'wood',  shop = 'Craftsdwarfs', item = 'WOOD' } },
}

local FREQ_TICKS = {                      -- a DF month is 28 days of 1200 ticks
    OneTime = 0, Daily = 1200, Monthly = 33600, Seasonally = 100800, Yearly = 403200,
}

local function spec_for(jname)
    return JOB_SPEC[jname]
end

local function now_tick()
    -- cur_year_tick wraps every year, so a schedule needs the absolute one
    return df.global.cur_year * 403200 + df.global.cur_year_tick
end

local function built(b)
    local ok, done = pcall(function()
        return b:getBuildStage() >= b:getMaxBuildStage()
    end)
    return ok and done
end

-- The (material, workshop, reagent) variant to use, or nil. Never a fallback: an earlier
-- version read `return want and nil or fallback`, which is `fallback` in every branch, so
-- a brew order went to the carpenter exactly as its comment promised it would not.
local function variant_for(jname, material)
    local variants = JOB_SPEC[jname]
    -- a name that is not a real df.job_type would blow up on the order write; measured,
    -- `ConstructBarrel` was invented from memory and the real one is `MakeBarrel`
    if not variants or df.job_type[jname] == nil then return nil end
    for _, v in ipairs(variants) do
        if material == nil or material == '' or material == 'any' or material == v.mat then
            local want = df.workshop_type[v.shop]
            for _, b in ipairs(w.buildings.all) do
                if df.building_workshopst:is_instance(b) and b.type == want and built(b) then
                    return v, b
                end
            end
        end
    end
    return nil
end

-- ---------------------------------------------------------------- conditions
-- How many of an item the fort holds, ignoring what is already spoken for. `mat_token`
-- narrows it the way a real condition does — `BAR (ASH)`, not any bar.
local function stock_of(item_name, mat_token)
    local t = df.item_type[item_name]
    if t == nil then return nil end
    local mi = nil
    if mat_token and mat_token ~= '' then
        mi = dfhack.matinfo.find(mat_token)
        if not mi then return nil end
    end
    local n = 0
    for _, it in ipairs(w.items.all) do
        if it:getType() == t and not (it.flags.in_job or it.flags.forbid
                                      or it.flags.removed) then
            if not mi or (it:getMaterial() == mi.type
                          and it:getMaterialIndex() == mi.index) then
                n = n + 1
            end
        end
    end
    return n
end

local function cond_holds(c)
    if not c or not c.item or c.item == '' then return true end
    local have = stock_of(c.item, c.material)
    if have == nil then return false end
    local v = c.value or 0
    if c.cmp == 'GreaterThan' then return have > v end
    if c.cmp == 'AtLeast' then return have >= v end
    if c.cmp == 'AtMost' then return have <= v end
    if c.cmp == 'Exactly' then return have == v end
    return have < v                        -- LessThan, the default
end

-- Write the condition onto the order itself, so it reads in-game and through
-- `orders export` the way a player's does, even though we are the ones evaluating it.
local function attach_condition(o, c)
    if not c or not c.item or c.item == '' then return end
    local ok = pcall(function()
        o.item_conditions:insert('#', { new = df.manager_order_condition_item })
        local cond = o.item_conditions[#o.item_conditions - 1]
        cond.compare_type = df.logic_condition_type[c.cmp or 'LessThan']
        cond.compare_val = c.value or 0
        cond.item_type = df.item_type[c.item]
        cond.item_subtype = -1
        if c.material and c.material ~= '' then
            local mi = dfhack.matinfo.find(c.material)
            if mi then cond.mat_type, cond.mat_index = mi.type, mi.index end
        end
    end)
    return ok
end

-- ---------------------------------------------------------------- the ledger
-- What the agent has asked for and not yet received, plus the schedule it asked for.
--
-- This, not the DF order, is the source of truth. DF retires a work order the moment the
-- jobs queued against it are gone, whatever amount_left still says — measured: an order
-- for 6 with 5 jobs queued ran 6 -> 5 -> 4 -> 3 -> 2 -> 1 and then vanished, having
-- produced five beds. On a normal fort DF's own dispatcher tops the queue back up before
-- that happens; on ours it never runs. So each df.manager_order mirrors ONE BATCH and the
-- rest of the request lives here.
_G.BONSAI_ORDERS = _G.BONSAI_ORDERS or {}

-- ...and on disk beside the actions file, because a Lua global dies with the DF process.
-- A mid-episode restart — a crash, a watchdog, a reload to inspect something — used to
-- take the outstanding remainder with it silently: the agent had asked for twelve beds,
-- five were queued, and the other seven simply stopped existing. The ledger is small and
-- flat, so one tab-separated line per order is enough and needs no JSON.
local LEDGER = path .. '.orders'

local function save_ledger()
    local fh = io.open(LEDGER, 'w')
    if not fh then return end
    for _, e in ipairs(_G.BONSAI_ORDERS) do
        local cd = e.cond or {}
        fh:write(table.concat({
            e.job, e.amount, e.material or '', e.freq, e.remaining,
            e.next_check or 0, e.fired and 1 or 0,
            cd.item or '', cd.cmp or '', cd.value or 0, cd.material or '',
        }, '\t'), '\n')
    end
    fh:close()
end

local function load_ledger()
    -- Once per DF process, not once per dispatch. Reloading whenever the live table
    -- happens to be empty resurrects orders that were deliberately cleared — it undid
    -- the reset in bonsai-ordercheck and brought back a bed order that then answered for
    -- a craft order's jobs, failing three cases that had nothing to do with it.
    if _G.BONSAI_LEDGER_LOADED then return end
    _G.BONSAI_LEDGER_LOADED = true
    if #_G.BONSAI_ORDERS > 0 then return end     -- the live copy wins
    local fh = io.open(LEDGER, 'r')
    if not fh then return end
    for line in fh:lines() do
        local f = {}
        for tok in string.gmatch(line .. '\t', '([^\t]*)\t') do f[#f + 1] = tok end
        if f[1] and f[1] ~= '' and JOB_SPEC[f[1]] then
            _G.BONSAI_ORDERS[#_G.BONSAI_ORDERS + 1] = {
                job = f[1], amount = tonumber(f[2]) or 0, material = f[3],
                freq = FREQ_TICKS[f[4]] and f[4] or 'OneTime',
                remaining = tonumber(f[5]) or 0, next_check = tonumber(f[6]) or 0,
                fired = f[7] == '1',
                cond = (f[8] ~= '' and df.item_type[f[8]] ~= nil) and {
                    item = f[8], cmp = f[9], value = tonumber(f[10]) or 0,
                    material = f[11],
                } or nil,
            }
        end
    end
    fh:close()
end

load_ledger()

local function place_order(rec)
    for _, e in ipairs(_G.BONSAI_ORDERS) do
        if e.job == rec.job and e.material == rec.material
            and (e.cond and e.cond.item or '') == (rec.cond and rec.cond.item or '')
            and e.freq == rec.freq then
            -- restating an order updates it rather than stacking a second copy, and the
            -- new terms are re-checked at once: leaving next_check alone meant an agent
            -- that raised a threshold had to wait out the old schedule before anything
            -- happened, which reads as the verb having been ignored
            e.amount, e.cond, e.material = rec.amount, rec.cond, rec.material
            e.next_check = 0
            if e.freq == 'OneTime' then e.remaining, e.fired = rec.amount, false end
            return e
        end
    end
    rec.remaining = 0
    rec.next_check = 0
    _G.BONSAI_ORDERS[#_G.BONSAI_ORDERS + 1] = rec
    return rec
end

local function outstanding(jname)
    local n = 0
    for _, e in ipairs(_G.BONSAI_ORDERS) do
        if e.job == jname then n = n + e.remaining end
    end
    return n
end

local function dispatch_orders()
    local made = 0
    local t = now_tick()
    for _, e in ipairs(_G.BONSAI_ORDERS) do
        -- 1. re-arm on schedule. The condition is what makes an order quiet, so it is
        --    checked here rather than being folded into the amount.
        if e.remaining <= 0 and t >= (e.next_check or 0) then
            if cond_holds(e.cond) then
                e.remaining = e.amount
                e.fired = true
            end
            -- OneTime with an unmet condition waits rather than being discarded; DF
            -- shows exactly that state as validated-but-not-active.
            e.next_check = t + (FREQ_TICKS[e.freq] > 0 and FREQ_TICKS[e.freq] or 1200)
        end

        -- 2. dispatch what is armed
        local variant, shop = variant_for(e.job, e.material)
        if e.remaining > 0 and variant and shop then
            local cap = 5
            pcall(function() cap = shop.profile.max_general_orders end)
            local batch = math.min(e.remaining, math.max(0, cap - #shop.jobs), 10)
            local live = cond_holds(e.cond)
            if batch > 0 and live then
                local o = df.manager_order:new()
                local mo = w.manager_orders
                o.id = mo.manager_order_next_id
                mo.manager_order_next_id = mo.manager_order_next_id + 1
                o.job_type = df.job_type[e.job]
                o.amount_left, o.amount_total = batch, batch
                o.frequency = df.workquota_frequency_type[e.freq] or 0
                o.max_workshops, o.workshop_id = 0, -1
                pcall(function() o.material_category[variant.mat] = true end)
                attach_condition(o, e.cond)
                o.status.validated = true      -- we are the manager; say so out loud
                o.status.active = true         -- the condition holds, or we would not be here
                mo.all:insert('#', o)

                local queued = 0
                for _ = 1, batch do
                    local item = free_material(df.item_type[variant.item])
                    if not item then break end
                    local job = df.job:new()
                    job.job_type = o.job_type
                    job.pos = xyz2pos(shop.centerx, shop.centery, shop.z)
                    job.flags.by_manager = true
                    job.order_id = o.id
                    pcall(function() job.material_category[variant.mat] = true end)
                    dfhack.job.addGeneralRef(job, df.general_ref_type.BUILDING_HOLDER, shop.id)
                    shop.jobs:insert('#', job)
                    dfhack.job.linkIntoWorld(job, true)
                    local ok = pcall(function()
                        dfhack.job.attachJobItem(job, item, df.job_role_type.Reagent, 0, -1)
                    end)
                    if ok and #job.items > 0 then
                        queued = queued + 1
                    else
                        -- a job with no reagent is cancelled by DF and silently removed
                        pcall(function() dfhack.job.removeJob(job) end)
                        break
                    end
                end
                -- the order must describe exactly what was queued, or DF's count
                -- outlives the work
                if queued == 0 then
                    for i = #mo.all - 1, 0, -1 do
                        if mo.all[i] == o then mo.all:erase(i) end
                    end
                else
                    o.amount_left, o.amount_total = queued, queued
                    e.remaining = e.remaining - queued
                    made = made + queued
                end
            end
        end
    end
    -- a one-time order that has been delivered is done with; a repeating one stays
    for i = #_G.BONSAI_ORDERS, 1, -1 do
        local e = _G.BONSAI_ORDERS[i]
        if e.freq == 'OneTime' and e.fired and e.remaining <= 0 then
            table.remove(_G.BONSAI_ORDERS, i)
        end
    end
    return made
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

-- Split on tabs, KEEPING empty fields. The obvious `gmatch("[^\t]+")` drops them, so a
-- request that leaves one optional argument blank silently shifts every argument after
-- it — measured: `add_workorder ConstructBed 20 wood BED LessThan 5 <blank> Daily`
-- arrived with frequency in the material slot and ran as a one-off.
local function split(line)
    local t, start = {}, 1
    while true do
        local sep = string.find(line, "\t", start, true)
        if not sep then t[#t + 1] = string.sub(line, start); break end
        t[#t + 1] = string.sub(line, start, sep - 1)
        start = sep + 1
    end
    return t
end

-- Placement cursor, persisted in a Lua global for the whole episode (globals survive
-- between dfhack-run calls). Without it every create_stockpile call recomputed the same
-- spots relative to the first citizen, so only the FIRST round ever placed anything and
-- the development term could be earned exactly once per episode.

-- ---------------------------------------------------------------- rooms and zones
-- What turns a dug hole into a fort. The guide spends its middle third here: a bedroom
-- per dwarf, a dining hall, a meeting area, and the furniture that makes a room count.
--
-- civzone_type runs to 97 on this build and the player-facing zones live at the TOP of
-- it вЂ” Bedroom is 92, not something near Home. Reading the low end of the enum finds
-- MeadHall and ThroneRoom, which are worldgen site vocabulary, and picking one of those
-- would produce a zone the fort never uses. Enumerated live rather than remembered.
local ZONE_KINDS = {
    bedroom      = 'Bedroom',
    dining       = 'DiningHall',
    meeting      = 'MeetingHall',
    pasture      = 'Pen',
    office       = 'Office',
    gather_fruit = 'PlantGathering',
    dormitory    = 'Dormitory',
    refuse       = 'Dump',
    barracks     = 'Barracks',
    tomb         = 'Tomb',
}

-- ---------------------------------------------------------------- stockpiles
-- What a pile accepts is NOT the `settings.flags` bits. Measured live on a fort with a
-- claimable bar lying two tiles from a pile whose every flag was on: zero hauling jobs
-- over 2000 ticks. DF matches items against the PER-CATEGORY material vectors, and a
-- freshly constructed pile has them at length 0 — it accepts nothing, no matter what the
-- flags say. Three piles built by this verb had been sitting inert on the test fort,
-- which is why its wagon was still fully loaded three game days after embark.
--
-- DFHack already solves this and its own quickfort uses the solution: the .dfstock
-- presets in hack/data/stockpiles, applied through plugins.stockpiles.import_settings.
-- Importing `library/cat_stone` sets flags.stone AND fills stone.mats — verified live,
-- 0 -> 343 materials, with an un-imported category left at 0 as the control. Filling
-- those vectors ourselves would mean guessing their sizes out of the raws, which is the
-- same remembering that has produced invented DF names three times here.
--
-- The preset is spelled `sheets` while the settings flag is spelled `sheet`. They are
-- not interchangeable, and the alias table below is the only place that difference lives.
local PILE_CATEGORIES = {
    'ammo', 'animals', 'armor', 'bars_blocks', 'cloth', 'coins', 'corpses',
    'finished_goods', 'food', 'furniture', 'gems', 'leather', 'refuse', 'sheets',
    'stone', 'weapons', 'wood',
}

local PILE_ALIAS = {
    drink = 'food', sheet = 'sheets', bars = 'bars_blocks', blocks = 'bars_blocks',
    goods = 'finished_goods', ore = 'stone', misc = 'finished_goods',
}

local function pile_category(name)
    if not name or name == '' then return nil end
    local want = PILE_ALIAS[name] or name
    for _, c in ipairs(PILE_CATEGORIES) do
        if c == want then return c end
    end
    return nil                                  -- refuse rather than substitute
end

-- Apply DFHack's shipped preset for each category. The modes are DFHack's own and they
-- do NOT do what their names suggest — measured on a pile accepting all 17 categories:
--
--   'enable'   adds the category (0 -> 343 stone materials)
--   'disable'  DID NOTHING: 17 categories on before, 17 after, stone.mats still 343
--   'set'      replaces wholesale: 17 categories -> 1, stone.mats 343 -> 0
--
-- So narrowing a pile is 'set' with the one category wanted. The first draft narrowed by
-- disabling all seventeen and then enabling one, which reported success and left the pile
-- exactly as it was.
local function pile_apply(pile, cats, mode)
    local sp
    if not pcall(function() sp = require('plugins.stockpiles') end) or not sp then
        return false
    end
    local any = false
    for _, cat in ipairs(cats) do
        local ok = pcall(function()
            sp.import_settings('library/cat_' .. cat,
                { id = pile.id, mode = mode or 'enable' })
        end)
        any = any or ok
    end
    return any
end

-- Does this pile accept anything at all? The question every stockpile case should have
-- been asking: counting piles proved they existed, never that they worked.
local function pile_accepts(pile)
    local n = 0
    pcall(function()
        for k, v in pairs(pile.settings.flags) do
            if type(v) == 'boolean' and v then n = n + 1 end
            local _ = k
        end
    end)
    return n
end

-- A civzone needs three things that are each optional to DFHack and each fatal to omit:
-- abstract = true, or constructBuilding simply fails; extents cast through
-- df.reinterpret_cast, because a raw uint8_t array assigned afterwards silently does not
-- take; and spec_sub_flag.active, without which the zone exists and does nothing.
local function make_zone(kind, x, y, z, width, height)
    local sub = df.civzone_type[ZONE_KINDS[kind] or '']
    if sub == nil then return nil end
    local area = width * height
    local ext = df.reinterpret_cast(df.building_extents_type, df.new('uint8_t', area))
    for i = 0, area - 1 do ext[i] = 1 end
    local b = dfhack.buildings.constructBuilding {
        type = df.building_type.Civzone, subtype = sub, abstract = true,
        pos = xyz2pos(x, y, z), width = width, height = height,
    }
    if not b then return nil end
    b.room.extents = ext
    b.room.x, b.room.y, b.room.width, b.room.height = x, y, width, height
    pcall(function() b.spec_sub_flag.active = true end)
    return b
end

-- Give a room to a dwarf. setOwner early-returns `true` when the zone already names that
-- unit, so writing assigned_unit_id first makes the call a no-op that reports success
-- while owned_buildings stays empty вЂ” the same one-sided-link trap as seating a noble.
local function own_room(b, unit)
    if not (b and unit) then return false end
    b.assigned_unit_id = -1
    local ok = pcall(function() dfhack.buildings.setOwner(b, unit) end)
    if not ok then return false end
    for _, owned in ipairs(unit.owned_buildings) do
        if owned == b then return true end
    end
    return false
end

-- A citizen by id, or one that does not already have a room.
local function pick_citizen(who, want_roomless)
    if who and who ~= '' and who ~= 'best' then
        for _, u in ipairs(cits) do
            if tostring(u.id) == who then return u end
        end
        return nil
    end
    if want_roomless then
        for _, u in ipairs(cits) do
            if #u.owned_buildings == 0 then return u end
        end
    end
    return cits[1]
end

-- Furniture the agent can install, and the item each one is made from. A bed built from
-- a table is not a soft failure: constructBuilding takes the item and DF cancels the job.
local FURNITURE = {
    bed     = { building = 'Bed',     item = 'BED' },
    table_  = { building = 'Table',   item = 'TABLE' },
    chair   = { building = 'Chair',   item = 'CHAIR' },
    door    = { building = 'Door',    item = 'DOOR' },
    cabinet = { building = 'Cabinet', item = 'CABINET' },
    coffer  = { building = 'Box',     item = 'BOX' },
    coffin  = { building = 'Coffin',  item = 'COFFIN' },
}
FURNITURE.table = FURNITURE.table_

-- A made piece of furniture standing free. `contained_items[].use == 0` distinguishes the
-- item a building IS from stock it merely holds, which is why a filter that rejected
-- everything held by a building could not find the chair a workshop had just produced.
local function free_furniture(item_name)
    local want = df.item_type[item_name]
    if want == nil then return nil end
    for _, it in ipairs(w.items.all) do
        if it:getType() == want and not it.flags.in_building then
            local usable = reach and reach.item(it, REACH_GROUPS)
                or not (it.flags.forbid or it.flags.in_job or it.flags.removed
                        or it.flags.foreign)
            if usable then return it end
        end
    end
    return nil
end

_G.BONSAI_PLACE = _G.BONSAI_PLACE or { stock = 0, shop = 0, dig = nil,
                                      zone = 0, furn = 0, build = 0 }
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

-- The ring runs out, and when it does every placing verb stops working forever.
--
-- Measured on the test fort after five battery runs: `build_workshop`, `create_stockpile`
-- and `create_zone` all placed nothing while an independent scan found free 2x2 and 3x3
-- sites a few tiles away. site() walks eight compass points and widens by three every
-- eighth step, so it samples an annulus; once those samples are occupied it keeps
-- proposing the same taken spots and the verb reports zero for the rest of the episode.
--
-- So: try the ring first, because it keeps the fort's layout tidy and spread out, then
-- fall back to a plain outward scan and take the first place the design actually fits.
-- A refusal after this one means the fort really has no room.
local function find_site(bw, bh, radius, cursor, tries, for_digging)
    local function fits(x, y, z)
        if not reach then return true end
        if for_digging then return (reach.dig_site(x, y, z, bw, bh, REACH_GROUPS)) end
        return (reach.site(x, y, z, bw, bh, REACH_GROUPS))
    end
    for i = 0, (tries or 48) - 1 do
        local x, y, z = site((cursor or 0) + i, radius or 6)
        if x and fits(x, y, z) then return x, y, z end
    end
    if not u1 then return nil end
    for r = 2, 30 do
        for dx = -r, r do
            for dy = -r, r do
                -- only the ring's edge, so the scan grows outward instead of re-testing
                if math.abs(dx) == r or math.abs(dy) == r then
                    local x, y, z = u1.pos.x + dx, u1.pos.y + dy, u1.pos.z
                    if fits(x, y, z) then return x, y, z end
                end
            end
        end
    end
    return nil
end

-- ---------------------------------------------------------------- the food chain
-- A fort that cannot farm is on a countdown. The measured year under the earlier verb
-- set ended drink 12 -> 0 with nothing planted and two of seven dwarves dead, so this is
-- the root of the survival tranche: a plot, a crop on it, and a kitchen that is not
-- allowed to eat the seed corn.

-- The plant raws index for a crop id, e.g. MUSHROOM_HELMET_PLUMP.
local function plant_index(id)
    for i, p in ipairs(w.raws.plants.all) do
        if p.id == id then return i, p end
    end
    return nil
end

-- Seeds the fort actually holds, as {id -> count}, so "best" means plantable now rather
-- than whatever the raws list first.
local function seed_counts()
    local counts = {}
    for _, it in ipairs(w.items.all) do
        if it:getType() == df.item_type.SEEDS and not it.flags.rotten then
            local mi = dfhack.matinfo.decode(it:getMaterial(), it:getMaterialIndex())
            if mi and mi.plant then
                counts[mi.plant.id] = (counts[mi.plant.id] or 0) + 1
            end
        end
    end
    return counts
end

-- Does this plant grow underground? Getting this wrong is silent: plump helmet is the
-- obvious staple and grows nothing at all in a surface plot, while the plot still reads
-- as built and planted. Measured — this code's own first farm went outdoors and was
-- sown with plump helmet.
local function subterranean(p)
    for k, v in pairs(p.flags) do
        if v == true and type(k) == 'string' and k:match('^BIOME_SUBTERRANEAN') then
            return true
        end
    end
    return false
end

-- The crops the fort has seed for, best first: something brewable ahead of something
-- merely edible, then whatever there is most of. Drink is what a fort runs out of first.
local function crops_by_preference()
    local list = {}
    for id, n in pairs(seed_counts()) do
        local idx, p = plant_index(id)
        if idx then
            list[#list + 1] = { id = id, idx = idx, n = n,
                                drink = p.flags.DRINK or false,
                                under = subterranean(p) }
        end
    end
    table.sort(list, function(x, y)
        if x.drink ~= y.drink then return x.drink end
        if x.n ~= y.n then return x.n > y.n end
        return x.id < y.id
    end)
    return list
end

-- The best crop for ground of a given kind, or nil if the fort has no seed for it.
local function best_seed(want_subterranean)
    for _, e in ipairs(crops_by_preference()) do
        if e.under == want_subterranean then return e.id, e.n end
    end
    return nil
end




-- Soil a crop will actually grow in. Farm plots need soil or muddied stone, and the
-- staple crop is subterranean — plump helmet carries BIOME_SUBTERRANEAN_WATER, so a plot
-- out in the sun grows nothing and reads as a working farm anyway.
local SOIL_MATS = {
    [df.tiletype_material.SOIL] = true,
    [df.tiletype_material.GRASS_LIGHT] = true,
    [df.tiletype_material.GRASS_DARK] = true,
    [df.tiletype_material.GRASS_DRY] = true,
    [df.tiletype_material.GRASS_DEAD] = true,
}

local function plantable(x, y, z, want_indoors)
    local ok, tt = pcall(function() return dfhack.maps.getTileType(x, y, z) end)
    if not ok or not tt then return false end
    local at = df.tiletype.attrs[tt]
    if at.shape ~= df.tiletype_shape.FLOOR or not SOIL_MATS[at.material] then
        return false
    end
    if dfhack.buildings.findAtTile(xyz2pos(x, y, z)) then return false end
    -- Soil a farmer cannot walk to is not farmland. Sealed pockets of soil exist all
    -- over an embark, and a plot on one reads as built and sown and grows nothing.
    if reach and not reach.tile(x, y, z, REACH_GROUPS) then return false end
    if want_indoors then
        local des = dfhack.maps.getTileFlags(x, y, z)
        if not des or des.outside then return false end
    end
    return true
end

-- Find a w x h block of plantable floor that suits the crop actually intended.
--
-- Which ground is right depends on WHAT is to be planted, not on the fort being dwarven.
-- This embark happened to ship six crops that are all subterranean, so a surface plot
-- would have grown nothing — and the first version of this built one and reported
-- success — but an embark carrying wheat or another surface plant wants the opposite.
-- So: take the intended crop (named, or the best one the fort has seed for), demand
-- ground that matches it, and fall back through the remaining crops rather than
-- building somewhere nothing will grow.
--
-- The search runs DOWN from the citizen's level as well as across it: dug-out soil is
-- under the embark, and an earlier pass scanned only the dwarf's own z and found nothing
-- while 165 usable tiles sat a few levels below.
local function farm_site(pw, ph, want_plant)
    if not u1 then return nil end

    local candidates = {}
    if want_plant and want_plant ~= '' and want_plant ~= 'best' then
        local idx, p = plant_index(want_plant)
        if not idx then return nil end          -- asked for a crop that does not exist
        candidates[1] = { id = want_plant, under = subterranean(p) }
    else
        candidates = crops_by_preference()
    end
    if #candidates == 0 then return nil end     -- no seed at all: nothing to plant

    for _, crop in ipairs(candidates) do
        for dz = 0, -10, -1 do
            local z = u1.pos.z + dz
            for r = 1, 30 do
                for dx = -r, r do
                    for dy = -r, r do
                        local x0, y0 = u1.pos.x + dx, u1.pos.y + dy
                        local all = true
                        for x = x0, x0 + pw - 1 do
                            for y = y0, y0 + ph - 1 do
                                if not plantable(x, y, z, crop.under) then all = false end
                            end
                        end
                        if all then return x0, y0, z, crop.id end
                    end
                end
            end
        end
    end
    return nil
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
            -- Pin the shaft head for the whole FORT, not the whole process. Citizen[1]
            -- wanders, so using its live position started a fresh one-tile shaft at a
            -- new spot on every call (observed: 96,91 then 95,98) — orphaned
            -- designations that connect to nothing and can never be reached.
            --
            -- Pinning it in a Lua global fixed that only until the next reload: the
            -- global is per DF process, so after a save/load the origin re-pinned to
            -- wherever citizen[1] happened to stand and the fort started a SECOND
            -- orphan shaft, leaving the first one's designations stranded at z-1 with
            -- reachable=false. Measured on a reloaded year-3 fort: shaft head 73,44
            -- while every outstanding dig job sat around 104,83.
            --
            -- So recover the origin from the map itself, which is in the save: if the
            -- fort already has a carved stairway, that IS the shaft, and digging
            -- continues from it.
            local function existing_shaft()
                for _, u in ipairs(cits) do
                    for r = 0, 25 do
                        for dx = -r, r do
                            for dy = -r, r do
                                local x, y, z = u.pos.x + dx, u.pos.y + dy, u.pos.z
                                local okt, tt = pcall(function()
                                    return dfhack.maps.getTileType(x, y, z)
                                end)
                                if okt and tt then
                                    local sh = df.tiletype.attrs[tt].shape
                                    if sh == df.tiletype_shape.STAIR_DOWN
                                        or sh == df.tiletype_shape.STAIR_UPDOWN then
                                        return { x, y, z }
                                    end
                                end
                            end
                        end
                    end
                end
                return nil
            end
            P.dig = P.dig or existing_shaft() or { u1.pos.x, u1.pos.y, u1.pos.z }
            local ox, oy, oz = P.dig[1], P.dig[2], P.dig[3]
            local placed = 0
            local DIG = df.tile_dig_designation
            local function mark(x, y, z, kind)
                if placed >= n then return end
                pcall(function()
                    local des = dfhack.maps.getTileFlags(x, y, z)
                    if not des then return end
                    -- Played by hand, DF cancelled work here in its own words:
                    -- "cancels Dig: Dangerous terrain." A tile holding liquid is one a
                    -- dwarf will refuse or drown in, and neither shows up in a
                    -- designation count — the batch just quietly never finishes.
                    if (des.flow_size or 0) > 0 then return end
                    local tt = dfhack.maps.getTileType(x, y, z)
                    local sh = tt and df.tiletype.attrs[tt].shape
                    -- only solid rock is diggable; flagging air or an existing floor
                    -- silently achieves nothing
                    if kind == DIG.Default and sh ~= df.tiletype_shape.WALL then return end
                    -- A tile that ALREADY carries exactly this designation is not work.
                    -- Without this the verb re-wrote the same tiles every call and counted
                    -- each rewrite: on a fort whose shaft region was fully designated it
                    -- reported `designate_dig=40` while the map went 186 -> 186. That is
                    -- this project's defining failure wearing the count as a disguise —
                    -- the number measured intent, not effect. DF clears `des.dig` back to
                    -- No once it has turned the designation into a job, so a tile still
                    -- holding `kind` is one still pending, and re-writing it achieves
                    -- nothing at all.
                    if des.dig == kind then return end
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
            -- A CHAMBER off each landing, not spokes. This used to carve four one-tile
            -- arms at radii 1..3, which is connected and diggable and useless: nothing
            -- that needs floor area ever fits. Measured — build_farm_plot refused for
            -- want of a 3x3 of dug soil while the fort had plenty of dug tiles, all of
            -- them one tile wide. A room hangs off the shaft so its first column is
            -- adjacent to the stair, which keeps every tile reachable.
            local len = math.max(1, math.min(tonumber(a[3]) or 4, 10))
            local wide = math.max(1, math.min(tonumber(a[4]) or 3, 10))
            local DIRS = { { 1, 0 }, { 0, 1 }, { -1, 0 }, { 0, -1 } }
            P.digring = (P.digring or 0)
            -- How far out a chamber may start. Bounded so a saturated fort cannot walk
            -- this to the map edge looking for virgin rock.
            local MAX_REACH = 30

            local function at(step, side, d)
                if d[1] ~= 0 then return ox + d[1] * step, oy + side end
                return ox + side, oy + d[2] * step
            end

            -- Is there anything left to cut at this distance: an undug wall nobody has
            -- already marked.
            local function fresh_step(z, d, step, hh)
                for side = -hh, hh do
                    local x, y = at(step, side, d)
                    local ok, des = pcall(function()
                        return dfhack.maps.getTileFlags(x, y, z)
                    end)
                    if ok and des and des.dig == DIG.No then
                        local tt = dfhack.maps.getTileType(x, y, z)
                        if tt and df.tiletype.attrs[tt].shape == df.tiletype_shape.WALL then
                            return true
                        end
                    end
                end
                return false
            end

            -- Start from the FRONTIER, not from the shaft.
            --
            -- `len` used to mean "the first len steps out", so once those were designated
            -- the verb could never extend the fort again: on the test fort it reported 0
            -- with 374 designations standing and virgin rock a few tiles further out.
            -- Walking outward to the first step that still has undug, unmarked wall fixes
            -- that WITHOUT orphaning anything — everything between the shaft and the
            -- frontier is by definition already designated, so the new chamber stays
            -- connected to the fort through tiles that are going to be dug. That
            -- connectivity is the whole reason to derive the offset from the map instead
            -- of from a call counter: an arbitrary band offset would sit behind a wall of
            -- virgin rock and be dug by nobody, while still reporting a healthy count.
            local function chamber(z, d)
                local hh = math.floor(wide / 2)
                local start
                for s = 1, MAX_REACH do
                    if fresh_step(z, d, s, hh) then start = s; break end
                end
                if not start then return end          -- nothing left this way
                for step = start, math.min(start + len - 1, MAX_REACH) do
                    for side = -hh, hh do
                        local x, y = at(step, side, d)
                        mark(x, y, z, DIG.Default)
                        if placed >= n then return end
                    end
                end
            end
            -- successive calls take the next side, so the fort grows instead of
            -- re-designating tiles that are already dug
            for dz = 1, depth do
                chamber(oz - dz, DIRS[((P.digring + dz - 1) % 4) + 1])
                if placed >= n then break end
            end
            -- The ring MUST advance whether or not anything was placed. It used to
            -- advance only under `placed > 0`, which was harmless while `mark()` counted
            -- its own no-ops: every call "placed" something, so the ring always turned.
            -- Adding the idempotence guard removed those phantom counts and turned that
            -- condition into a wedge — a call that finds its four sides already
            -- designated returns 0, the ring freezes, and `DIRS[((digring+dz-1)%4)+1]`
            -- re-walks the identical directions for the rest of the episode. The verb
            -- would report 0 forever and the fort would stop growing. Turning the ring is
            -- what makes the NEXT call look somewhere new, so it is exactly what must
            -- happen when this one found nothing.
            P.digring = P.digring + 1
            if placed > 0 then
                -- ask the engine to run its dig-job scan on the next tick
                pcall(function() df.global.process_dig = true end)
                pcall(function() df.global.process_jobs = true end)
            end
            c.designate_dig = c.designate_dig + placed
        end)
    elseif verb == "apply_template" then
        -- Stamp one of DFHack's shipped blueprints. The owner asked for exactly this and
        -- was explicit that it must be the game's own template system rather than a
        -- homegrown format:
        --     использование именно шаблонов внутри игры внутри двхака
        --
        -- The catalog owns the library, so this receives the quickfort NAME and the
        -- measured extent rather than looking anything up. Arguments:
        --   a[2] blueprint name as quickfort addresses it (library/tombs/Mini_Saracen.csv)
        --   a[3] width  a[4] height  a[5] z-levels
        --   a[6] start x  a[7] start y — the blueprint's own anchor, 1-indexed
        --   a[8] which blueprint INSIDE the file, or blank for the first one
        --
        -- That last one is a trap dressed as a default. A .csv holds several blueprints
        -- and `quickfort run <file>` runs the FIRST. library/pump_stack.csv opens with a
        -- #notes help section, so running the file printed a walkthrough and stamped
        -- nothing; library/tombs/Mini_Saracen.csv worked only because its first section
        -- happens to be #dig. Anything else must be named as -n /<label>.
        pcall(function()
            local name = a[2]
            local bw, bh = tonumber(a[3]), tonumber(a[4])
            local sx, sy = tonumber(a[6]) or 1, tonumber(a[7]) or 1
            if not (name and name ~= '' and bw and bh) then return end

            -- Find somewhere it actually fits. reach.site checks every tile is a floor a
            -- citizen can stand on and nothing is already there, which is the difference
            -- between stamping a room and stamping it into a wall.
            -- its own placement cursor: sharing the stockpile one made every call
            -- retry the same 48 spots and compete with piles for them
            -- WHICH fit test depends on what the blueprint does, and getting this
            -- wrong made the verb refuse every dig design on a fort full of stone: a
            -- workshop needs a free floor, a crypt needs solid rock a miner can reach.
            -- Same wall-is-not-walkable distinction bonsai-reach was written around.
            P.tmpl = (P.tmpl or 0)
            local digs = (a[9] or 'dig') == 'dig'
            local x0, y0, z0 = find_site(bw, bh, 6, P.tmpl, 48, digs)
            if not x0 then return end            -- refuse rather than stamp nowhere
            P.tmpl = P.tmpl + 1

            -- What is there before, inside the box the blueprint will cover.
            local function census()
                local des, bld = 0, 0
                for x = x0, x0 + bw - 1 do
                    for y = y0, y0 + bh - 1 do
                        local ok, d = pcall(function()
                            return dfhack.maps.getTileFlags(x, y, z0)
                        end)
                        if ok and d and d.dig ~= df.tile_dig_designation.No then
                            des = des + 1
                        end
                        if dfhack.buildings.findAtTile(xyz2pos(x, y, z0)) then
                            bld = bld + 1
                        end
                    end
                end
                return des + bld
            end
            local before = census()

            -- THE POSITION TRAP: quickfort's CLI lands the cursor on the blueprint's own
            -- start() cell, not on its top-left. start(6;6) run at 100,90 puts the corner
            -- at 95,85 — measured live. The apply_blueprint API does the opposite and
            -- ignores start() entirely, so the two entry points disagree by the anchor.
            local cx, cy = x0 + sx - 1, y0 + sy - 1
            local label = a[8]
            pcall(function()
                local cursor = string.format('%d,%d,%d', cx, cy, z0)
                if label and label ~= '' then
                    dfhack.run_command('quickfort', 'run', '-c', cursor,
                        name, '-n', '/' .. label)
                else
                    dfhack.run_command('quickfort', 'run', '-c', cursor, name)
                end
            end)

            -- quickfort prints its own statistics, which is not evidence: count the map.
            --
            -- Record the attempt whether or not anything changed, and say which. A caller
            -- cannot otherwise tell "there was nowhere to put it" from "it was already
            -- stamped here" — re-running a template over its own designations correctly
            -- changes nothing, and the battery was reporting that as a refusal of a site
            -- that exists.
            local after = census()
            _G.BONSAI_LAST_TEMPLATE = { name = name, x = x0, y = y0, z = z0,
                                        w = bw, h = bh, new = after - before }
            if after > before then
                c.apply_template = c.apply_template + 1
            end
        end)
    elseif verb == "create_stockpile" then
        pcall(function()
            local n = tonumber(a[2]) or 1
            -- A pile is placed WITH a type in DF's own UI — you pick from a menu. Ours
            -- placed an untyped one, which accepts nothing, so the catalog's claim that
            -- it "accepts the default everything" was false and every pile this verb had
            -- ever made was inert. Naming a category is the player's move; omitting it
            -- now means everything, which is what the contract always said.
            local want = a[3]
            local cats = PILE_CATEGORIES
            if want and want ~= '' and want ~= 'everything' then
                local cat = pile_category(want)
                if not cat then return end      -- refuse an unknown category
                cats = { cat }
            end
            for _ = 1, n do
                -- Walk the ring until one placement takes, the same way build_workshop
                -- does. A single attempt worked on an empty embark and silently placed
                -- nothing once the ring filled: measured on a fort with three
                -- stockpiles, `create_stockpile 1` reported 3 -> 3.
                local placed = false
                for _ = 1, 48 do
                    local x, y, z = find_site(2, 2, 4, P.stock, 8)
                    P.stock = P.stock + 1
                    if x then
                        pcall(function()
                            local b = dfhack.buildings.constructBuilding{
                                type = df.building_type.Stockpile, abstract = true,
                                pos = { x = x, y = y, z = z }, width = 2, height = 2 }
                            if b then
                                pile_apply(b, cats, 'enable')
                                c.create_stockpile = c.create_stockpile + 1
                                placed = true
                            end
                        end)
                    end
                    if placed then break end
                end
                if not placed then break end
            end
        end)
    elseif verb == "build_workshop" then
        -- Without a workshop no manager order can ever be worked, so `workorders_done`
        -- was structurally pinned at 0 and half the development weight was unearnable.
        pcall(function()
            local name = a[2] or "Carpenters"
            local sub = df.workshop_type[name]
            -- Refuse an unknown kind rather than substituting. This used to read
            -- `if sub == nil then sub = df.workshop_type.Carpenters end`, the same
            -- silent-substitution shape that turned `add_workorder NoSuchJobType 5`
            -- into five beds: the agent asks for a Still, gets a carpenter, and the
            -- brewing it was planning quietly never happens.
            if sub == nil then return end
            -- Masons and Craftsdwarfs work stone; the rest of what an early fort builds
            -- wants wood. A workshop may legitimately be made of either, so each order
            -- of preference falls back to the other — unlike a job reagent, where the
            -- wrong material gets the job cancelled.
            local item
            if name == "Masons" or name == "Craftsdwarfs" then
                item = free_material(df.item_type.BOULDER, df.item_type.WOOD)
            else
                item = free_material(df.item_type.WOOD, df.item_type.BOULDER)
            end
            if not item then return end          -- nothing to build it out of, so do not
                                                 -- claim we did
            -- Try many spots before giving up. One attempt was enough on an empty
            -- embark and silently did nothing once the ring filled: measured first on a
            -- fort with eight workshops and again at fifteen, where twelve attempts were
            -- no longer enough either. site() widens the ring every eight steps, so more
            -- attempts genuinely search outward rather than retrying the same ground.
            for _ = 1, 48 do
                -- Skip a spot nobody can reach before asking DF to build there: a
                -- workshop on unreachable ground takes its reagent, never gets built,
                -- and reads as a successful placement. find_site falls back to an
                -- outward scan once the ring is used up, which is what stopped this verb
                -- dead on a fort that still had room.
                local x, y, z = find_site(3, 3, 8, P.shop, 8)
                P.shop = P.shop + 1
                if x then
                    local b = dfhack.buildings.constructBuilding{
                        type = df.building_type.Workshop, subtype = sub,
                        pos = { x = x, y = y, z = z }, items = { item } }
                    -- Count it only if DF actually attached a build job with a reagent.
                    -- The old count was "constructBuilding returned something", which it
                    -- does even when the building is about to be cancelled and removed.
                    if b and #b.jobs > 0 and #b.jobs[0].items > 0 then
                        c.build_workshop = c.build_workshop + 1
                        return
                    end
                end
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
        -- BULK CREATION: make N of X, once. No condition, no schedule — those belong to
        -- add_workorder_conditional. They are one struct inside DF and two different
        -- things to want (tools/df_docs/open_decisions.md); merging them made the simple
        -- request step over five arguments it does not use.
        --
        --   add_workorder  ConstructBed  20  wood
        pcall(function()
            -- Refuse a job we have no workshop-and-reagent rule for. This used to read
            -- `... and a[2] or "ConstructBed"`, which silently turned a request for
            -- anything unknown into beds — measured: `add_workorder NoSuchJobType 5`
            -- queued five ConstructBed jobs.
            local jname = a[2]
            if not (jname and spec_for(jname)) then return end
            place_order {
                job = jname, amount = tonumber(a[3]) or 10,
                material = a[4] or "", freq = "OneTime", cond = nil,
            }
            c.add_workorder = c.add_workorder + dispatch_orders()
        end)
    elseif verb == "add_workorder_conditional" then
        -- AUTOMATION: watch a stock level and refill it without being asked again.
        -- Read off a hand-played fort, that is `MakeAsh x_/10 Daily WHILE LessThan 10 of
        -- BAR (ASH)` — the amount is the FULL order, and the condition is what makes it
        -- go quiet once the shelf is full.
        --
        --   add_workorder_conditional  ConstructBarrel  BARREL  5  10  LessThan  ""  Daily
        pcall(function()
            local jname = a[2]
            if not (jname and spec_for(jname)) then return end
            local item = a[3] or ""
            local value = tonumber(a[4]) or 0
            local amount = tonumber(a[5]) or 10
            local cmp = a[6] or "LessThan"
            local imaterial = a[7] or ""
            local freq = a[8] or "Daily"
            if item == "" or df.item_type[item] == nil then return end
            if df.logic_condition_type[cmp] == nil then cmp = "LessThan" end
            if FREQ_TICKS[freq] == nil then freq = "Daily" end
            place_order {
                job = jname, amount = amount, material = "", freq = freq,
                cond = { item = item, cmp = cmp, value = value, material = imaterial },
            }
            c.add_workorder_conditional = c.add_workorder_conditional + 1
            c.add_workorder = c.add_workorder + dispatch_orders()
        end)
    elseif verb == "create_zone" then
        -- Paint a zone. A dug room is not a bedroom until something says so.
        pcall(function()
            local kind = a[2]
            if not (kind and ZONE_KINDS[kind]) then return end
            local width = math.max(1, math.min(tonumber(a[3]) or 6, 20))
            local height = math.max(1, math.min(tonumber(a[4]) or width, 20))
            local x, y, z
            for _ = 1, 16 do
                local cx, cy, cz = find_site(width, height, 5, P.zone or 0, 8)
                P.zone = (P.zone or 0) + 1
                if cx then
                    x, y, z = cx, cy, cz
                    break
                end
            end
            if not x then return end
            if make_zone(kind, x, y, z, width, height) then
                c.create_zone = c.create_zone + 1
            end
        end)
    elseif verb == "assign_room" then
        -- Give a room to somebody. An unowned bedroom is furniture in a hole.
        pcall(function()
            local kind = a[2]
            local want = kind and ZONE_KINDS[kind] and df.civzone_type[ZONE_KINDS[kind]]
            local unit = pick_citizen(a[3], true)
            if not (want and unit) then return end
            for _, b in ipairs(w.buildings.all) do
                if b:getType() == df.building_type.Civzone and b:getSubtype() == want
                    and b.assigned_unit_id == -1 then
                    if own_room(b, unit) then
                        c.assign_room = c.assign_room + 1
                        return
                    end
                end
            end
        end)
    elseif verb == "place_furniture" then
        -- Install something already made. The item has to exist first: this verb does
        -- not build a bed, it puts one down.
        pcall(function()
            local spec = FURNITURE[a[2] or ""]
            if not spec then return end
            local count = math.max(1, math.min(tonumber(a[3]) or 1, 10))
            for _ = 1, count do
                local item = free_furniture(spec.item)
                if not item then break end
                local placed = false
                for _ = 1, 12 do
                    local x, y, z = site(P.furn or 0, 3)
                    P.furn = (P.furn or 0) + 1
                    if x and (not reach or reach.site(x, y, z, 1, 1, REACH_GROUPS)) then
                        local b = dfhack.buildings.constructBuilding {
                            type = df.building_type[spec.building],
                            pos = xyz2pos(x, y, z), items = { item },
                        }
                        -- same rule as build_workshop: only a build job that actually
                        -- carries a reagent counts, because constructBuilding returns a
                        -- building even when DF is about to cancel and remove it
                        if b and #b.jobs > 0 and #b.jobs[0].items > 0 then
                            c.place_furniture = c.place_furniture + 1
                            placed = true
                        end
                    end
                    if placed then break end
                end
                if not placed then break end
            end
        end)
    elseif verb == "set_dwarf_labor" then
        -- One dwarf, one labour. set_labor is a fort-wide switch; a player specialises.
        pcall(function()
            local unit = pick_citizen(a[2], false)
            local lid = df.unit_labor[a[3] or ""]
            if not (unit and lid) then return end
            local on = not (a[4] == "False" or a[4] == "false" or a[4] == "0")
            unit.status.labors[lid] = on
            c.set_dwarf_labor = c.set_dwarf_labor + 1
        end)
    elseif verb == "cancel_dwarf_job" then
        -- Free a dwarf who is doing something less important than what is needed now.
        pcall(function()
            local unit = pick_citizen(a[2], false)
            if not (unit and unit.job.current_job) then return end
            local job = unit.job.current_job
            if pcall(function() dfhack.job.removeJob(job) end) then
                c.cancel_dwarf_job = c.cancel_dwarf_job + 1
            end
        end)
    elseif verb == "configure_stockpile" then
        -- Narrow what a pile accepts. The guide's first act on a new stockpile is to
        -- remove stone and wood so bulk goods cannot crowd out food.
        --
        -- The old body walked `settings[<group>]` and flipped any boolean it found. Those
        -- groups hold VECTORS, not booleans, so it flipped almost nothing, and it never
        -- touched `settings.flags` at all — measured on three configured piles, every
        -- flag was still false and every material vector still empty. It reported success
        -- the whole time.
        pcall(function()
            local which = tonumber(a[2]) or 0
            local cat = pile_category(a[3])
            if not cat then return end          -- refuse an unknown category
            -- address a specific pile, so a fort with several can narrow them
            -- differently: one for food, one for wood, the way a player lays them out
            local piles = {}
            for _, b in ipairs(w.buildings.all) do
                if b:getType() == df.building_type.Stockpile then piles[#piles + 1] = b end
            end
            local target = piles[which + 1] or piles[1]
            if not target then return end
            -- Disable every category, then enable the one asked for. Explicit rather
            -- than leaning on DFHack's 'set' mode, whose clearing behaviour we have not
            -- measured — and an unmeasured assumption is what this verb was made of.
            if not pile_apply(target, { cat }, 'set') then return end

            -- Barrels and bins. The guide turns them off for a stone pile so wheelbarrows
            -- are used instead. These live on `storage`, NOT on the building and NOT in
            -- `settings` — enumerated live rather than guessed, because the first draft
            -- of this wrote `target.max_barrels`, which is not a field, and would have
            -- failed inside a pcall without saying so.
            local containers = (a[4] or 'True')
            local allow = not (containers == 'False' or containers == 'false')
            local tiles = (target.x2 - target.x1 + 1) * (target.y2 - target.y1 + 1)
            pcall(function()
                target.storage.max_barrels = allow and tiles or 0
                target.storage.max_bins = allow and tiles or 0
            end)
            if pile_accepts(target) > 0 then
                c.configure_stockpile = c.configure_stockpile + 1
            end
        end)
    elseif verb == "chop_trees" then
        -- Wood is the fort's first material and it runs out. Felling uses the same
        -- designation field as digging, set on a tile whose material is TREE.
        pcall(function()
            local n = math.max(1, math.min(tonumber(a[2]) or 10, 100))
            if not u1 then return end
            local marked = 0
            for r = 1, 25 do
                for dx = -r, r do
                    for dy = -r, r do
                        if marked >= n then break end
                        local x, y, z = u1.pos.x + dx, u1.pos.y + dy, u1.pos.z
                        local okt, tt = pcall(function() return dfhack.maps.getTileType(x, y, z) end)
                        if okt and tt and df.tiletype.attrs[tt].material == df.tiletype_material.TREE then
                            local des = dfhack.maps.getTileFlags(x, y, z)
                            if des and des.dig == df.tile_dig_designation.No
                                and (not reach or reach.adjacent(x, y, z, REACH_GROUPS)) then
                                des.dig = df.tile_dig_designation.Default
                                local blk = dfhack.maps.getTileBlock(xyz2pos(x, y, z))
                                if blk then blk.flags.designated = true end
                                marked = marked + 1
                            end
                        end
                    end
                end
                if marked >= n then break end
            end
            if marked > 0 then
                pcall(function() df.global.process_dig = true end)
                c.chop_trees = c.chop_trees + marked
            end
        end)
    elseif verb == "smooth" then
        -- Smoothing raises a room's value and is the step before engraving. It applies
        -- to dug stone, so it needs a fort that has dug some.
        pcall(function()
            local n = math.max(1, math.min(tonumber(a[2]) or 20, 200))
            if not u1 then return end
            local marked = 0
            for dz = 0, 8 do
                for dx = -12, 12 do
                    for dy = -12, 12 do
                        if marked >= n then break end
                        local x, y, z = u1.pos.x + dx, u1.pos.y + dy, u1.pos.z - dz
                        local okt, tt = pcall(function() return dfhack.maps.getTileType(x, y, z) end)
                        if okt and tt then
                            local at = df.tiletype.attrs[tt]
                            local stone = at.material == df.tiletype_material.STONE
                                or at.material == df.tiletype_material.MINERAL
                            local shape = at.shape
                            local smoothable = stone
                                and (shape == df.tiletype_shape.WALL
                                     or shape == df.tiletype_shape.FLOOR)
                            local des = smoothable and dfhack.maps.getTileFlags(x, y, z)
                            if des and des.smooth == 0
                                and (not reach or reach.adjacent(x, y, z, REACH_GROUPS)) then
                                des.smooth = 1
                                local blk = dfhack.maps.getTileBlock(xyz2pos(x, y, z))
                                if blk then blk.flags.designated = true end
                                marked = marked + 1
                            end
                        end
                    end
                end
                if marked >= n then break end
            end
            if marked > 0 then
                pcall(function() df.global.process_dig = true end)
                c.smooth = c.smooth + marked
            end
        end)
    elseif verb == "build_construction" then
        -- Walls, floors, ramps and stairs built out of stored material: how a fort makes
        -- space it did not dig, and how it seals what it did.
        pcall(function()
            local kindname = a[2] or "Floor"
            local sub = df.construction_type[kindname]
            if sub == nil then return end
            local count = math.max(1, math.min(tonumber(a[3]) or 1, 20))
            for _ = 1, count do
                local item = free_material(df.item_type.BOULDER, df.item_type.WOOD)
                if not item then break end
                local placed = false
                for _ = 1, 12 do
                    local x, y, z = site(P.build or 0, 6)
                    P.build = (P.build or 0) + 1
                    if x and (not reach or reach.site(x, y, z, 1, 1, REACH_GROUPS)) then
                        local b = dfhack.buildings.constructBuilding {
                            type = df.building_type.Construction, subtype = sub,
                            pos = xyz2pos(x, y, z), items = { item },
                        }
                        if b and #b.jobs > 0 and #b.jobs[0].items > 0 then
                            c.build_construction = c.build_construction + 1
                            placed = true
                        end
                    end
                    if placed then break end
                end
                if not placed then break end
            end
        end)
    elseif verb == "set_standing_order" then
        -- Fort-wide policy. Fifty of these exist as df.global.standing_orders_*, and the
        -- guide singles out refuse collection: leave it on and dwarves haul rotting
        -- vermin indoors, turn it off and the surface stays a rubbish tip.
        pcall(function()
            local name = a[2]
            if not name or name == "" then return end
            local key = "standing_orders_" .. name
            if df.global[key] == nil then return end
            local on = not (a[3] == "False" or a[3] == "false" or a[3] == "0")
            df.global[key] = on and 1 or 0
            c.set_standing_order = c.set_standing_order + 1
        end)
    elseif verb == "set_dig_priority" then
        -- Priority is NOT a field on the map block, which is why a first look concluded
        -- the mechanic did not exist on this build. It lives in a block_square_event of
        -- type designation_priority, indexed by pos % 16 and stored as priority * 1000 вЂ”
        -- read out of DFHack's own quickfort/dig.lua rather than guessed at.
        pcall(function()
            local want = math.max(1, math.min(tonumber(a[2]) or 4, 7))
            if not u1 then return end
            local P2 = P.dig or { u1.pos.x, u1.pos.y, u1.pos.z }
            local ox, oy, oz = P2[1], P2[2], P2[3]
            local touched = 0
            for dz = 0, 10 do
                for dx = -8, 8 do
                    for dy = -8, 8 do
                        local x, y, z = ox + dx, oy + dy, oz - dz
                        local okd, des = pcall(function()
                            return dfhack.maps.getTileFlags(x, y, z)
                        end)
                        if okd and des and des.dig ~= df.tile_dig_designation.No then
                            pcall(function()
                                local blk = dfhack.maps.getTileBlock(xyz2pos(x, y, z))
                                if not blk then return end
                                local pbse
                                for _, ev in ipairs(blk.block_events) do
                                    if ev:getType()
                                        == df.block_square_event_type.designation_priority then
                                        pbse = ev
                                    end
                                end
                                if not pbse then
                                    blk.block_events:insert('#',
                                        { new = df.block_square_event_designation_priorityst })
                                    pbse = blk.block_events[#blk.block_events - 1]
                                end
                                pbse.priority[x % 16][y % 16] = want * 1000
                                blk.flags.designated = true
                                touched = touched + 1
                            end)
                        end
                    end
                end
            end
            if touched > 0 then c.set_dig_priority = c.set_dig_priority + touched end
        end)
    elseif verb == "build_farm_plot" then
        -- Without this the fort eats what it embarked with and then starves. Plots need
        -- no material, so the failure mode is not a missing reagent but a plot on the
        -- wrong ground: subterranean crops grow nothing in the sun and the plot still
        -- looks built.
        pcall(function()
            local pw = math.max(1, math.min(tonumber(a[2]) or 3, 10))
            local ph = math.max(1, math.min(tonumber(a[3]) or pw, 10))
            local want_plant = a[4] or ""       -- name the crop, or let it choose
            local x, y, z, crop = farm_site(pw, ph, want_plant)
            if not x then return end
            local b = dfhack.buildings.constructBuilding {
                type = df.building_type.FarmPlot,
                pos = xyz2pos(x, y, z), width = pw, height = ph,
            }
            if not b then return end
            -- a plot takes no items to build, so finish it rather than leaving the fort
            -- waiting on a construction job that carries no reagent
            pcall(function() b:setBuildStage(b:getMaxBuildStage()) end)
            pcall(function() b.flags.exists = true end)
            -- sow it with the crop the ground was chosen for, so a plot is never left
            -- built-but-empty and never sown with something that cannot grow there
            local idx = crop and plant_index(crop) or nil
            if idx then for s = 0, 3 do b.plant_id[s] = idx end end
            c.build_farm_plot = c.build_farm_plot + 1
        end)
    elseif verb == "set_crop" then
        -- Which crop, in which season, PER PLOT: a surface plot and a dug-out one want
        -- different plants, and sowing the wrong one is invisible — the plot reads as
        -- planted and grows nothing.
        pcall(function()
            local want = a[2]
            local season = a[3]
            local n = 0
            for _, b in ipairs(w.buildings.all) do
                if b:getType() == df.building_type.FarmPlot then
                    local des = dfhack.maps.getTileFlags(b.x1, b.y1, b.z)
                    local underground = not (des and des.outside)
                    local crop = want
                    if not crop or crop == "" or crop == "best" then
                        crop = best_seed(underground)
                    end
                    local idx = crop and plant_index(crop) or nil
                    if idx then
                        if season == nil or season == "" or season == "all" then
                            for s = 0, 3 do b.plant_id[s] = idx end
                        else
                            local s = tonumber(season)
                            if s and s >= 0 and s <= 3 then b.plant_id[s] = idx end
                        end
                        n = n + 1
                    end
                end
            end
            if n > 0 then c.set_crop = c.set_crop + 1 end
        end)
    elseif verb == "set_kitchen_flag" then
        -- The two clicks that decide a second year: cooking seeds destroys next year's
        -- crop, and cooking drink turns the beer supply into meals.
        pcall(function()
            local item = a[2]                       -- SEEDS or DRINK
            local allowed = (a[3] == "true" or a[3] == "True" or a[3] == "1")
            local itype = df.item_type[item]
            if itype == nil then return end
            local k = df.global.plotinfo.kitchen
            local changed, reached = 0, 0
            -- one exclusion per (item type, material) the fort actually holds
            local seen = {}
            for _, it in ipairs(w.items.all) do
                if it:getType() == itype then
                    local mt, mi = it:getMaterial(), it:getMaterialIndex()
                    local key = mt .. ":" .. mi
                    if not seen[key] then
                        seen[key] = true
                        local at = -1
                        for i = 0, #k.item_types - 1 do
                            if k.item_types[i] == itype and k.mat_types[i] == mt
                                and k.mat_indices[i] == mi then at = i end
                        end
                        if allowed == (at < 0) then reached = reached + 1 end
                        if allowed then
                            if at >= 0 then
                                k.item_types:erase(at); k.item_subtypes:erase(at)
                                k.mat_types:erase(at); k.mat_indices:erase(at)
                                k.exc_types:erase(at)
                                changed = changed + 1
                            end
                        elseif at < 0 then
                            k.item_types:insert('#', itype)
                            k.item_subtypes:insert('#', it:getSubtype())
                            k.mat_types:insert('#', mt)
                            k.mat_indices:insert('#', mi)
                            k.exc_types:insert('#', 0)   -- 0 = cookery
                            changed = changed + 1
                        end
                    end
                end
            end
            -- Report reaching the requested state, not only changing it. DF ships with
            -- seeds already excluded from cooking, so a correct `set_kitchen_flag SEEDS
            -- false` looked like a failed verb.
            if changed > 0 or reached > 0 then
                c.set_kitchen_flag = c.set_kitchen_flag + 1
            end
        end)
    end
end
f:close()

-- Every dispatch is a visit from the manager: re-check each order's schedule and its
-- condition, and queue whatever is armed. This is the visit DF's own manager would pay
-- and never does on our forts.
local dispatched = dispatch_orders()
if dispatched > 0 then c.add_workorder = c.add_workorder + dispatched end
save_ledger()

local rep = {}
for k, v in pairs(c) do rep[#rep + 1] = k .. "=" .. v end
table.sort(rep)
print("APPLY " .. table.concat(rep, " "))
