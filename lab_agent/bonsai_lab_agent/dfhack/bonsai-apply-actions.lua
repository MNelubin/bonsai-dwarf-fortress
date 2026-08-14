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
            add_workorder_conditional = 0, build_farm_plot = 0, set_crop = 0,
            set_kitchen_flag = 0 }

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

-- The best crop for a plot in this place: something the fort has seed for, that grows
-- where the plot actually is, preferring one that can be brewed — drink is what a fort
-- runs out of first.
local function best_seed(want_subterranean)
    local best, best_n, best_drink = nil, -1, false
    for id, n in pairs(seed_counts()) do
        local idx, p = plant_index(id)
        if idx and subterranean(p) == want_subterranean then
            local drink = p.flags.DRINK or false
            if (drink and not best_drink) or (drink == best_drink and n > best_n) then
                best, best_n, best_drink = id, n, drink
            end
        end
    end
    return best, best_n
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
    if want_indoors then
        local des = dfhack.maps.getTileFlags(x, y, z)
        if not des or des.outside then return false end
    end
    return true
end

-- Find a w x h block of plantable floor where the fort's OWN seeds will grow.
--
-- A dwarven embark ships six crops and every one of them is subterranean — measured on
-- this fort: plump helmet, cave wheat, pig tail, sweet pod, dimple cup, quarry bush, all
-- BIOME_SUBTERRANEAN_WATER. So a surface plot is not a worse choice, it is a plot that
-- grows nothing, and an earlier version of this happily built one and reported success.
-- If the fort has not dug out any soil yet, the answer is to dig, not to farm outdoors.
--
-- The search runs DOWN from the citizen's level, not across it: the dug-out soil is
-- under the embark, and an earlier version scanned only the dwarf's own z and found
-- nothing while 165 usable tiles sat a few levels below.
local function farm_site(pw, ph)
    if not u1 then return nil end
    local want_indoors = true
    for id in pairs(seed_counts()) do
        local idx, p = plant_index(id)
        if idx and not subterranean(p) then want_indoors = false end
    end
    for dz = 0, -10, -1 do
        local z = u1.pos.z + dz
        for r = 1, 30 do
            for dx = -r, r do
                for dy = -r, r do
                    local x0, y0 = u1.pos.x + dx, u1.pos.y + dy
                    local all = true
                    for x = x0, x0 + pw - 1 do
                        for y = y0, y0 + ph - 1 do
                            if not plantable(x, y, z, want_indoors) then all = false end
                        end
                    end
                    if all then return x0, y0, z, want_indoors end
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
    elseif verb == "build_farm_plot" then
        -- Without this the fort eats what it embarked with and then starves. Plots need
        -- no material, so the failure mode is not a missing reagent but a plot on the
        -- wrong ground: subterranean crops grow nothing in the sun and the plot still
        -- looks built.
        pcall(function()
            local pw = math.max(1, math.min(tonumber(a[2]) or 3, 10))
            local ph = math.max(1, math.min(tonumber(a[3]) or pw, 10))
            local x, y, z, indoors = farm_site(pw, ph)
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
            _G.BONSAI_PLACE.farm_indoors = indoors
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

local rep = {}
for k, v in pairs(c) do rep[#rep + 1] = k .. "=" .. v end
table.sort(rep)
print("APPLY " .. table.concat(rep, " "))
