-- bonsai-apply-actions: deterministic evaluator-side dispatch of the agent's action
-- intents (anti-forgery). Reads agent_actions.txt (tab-separated: verb\targ1\targ2),
-- applies ONLY the allow-listed verbs, never executes agent code. Reports counts.
-- Kept in sync with game_scorer.ALLOWED_VERBS.
-- the actions file is named per episode; parallel forts must not read each
-- other's intents
local path = (...) or "/srv/df-bonsai/current/agent_actions.txt"
local mode = select(2, ...)
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
            add_workorder_conditional = 0, build_farm_plot = 0, brew_drink = 0, set_crop = 0,
            set_kitchen_flag = 0, create_zone = 0, assign_room = 0,
            place_furniture = 0, set_dwarf_labor = 0, cancel_dwarf_job = 0,
            configure_stockpile = 0, chop_trees = 0, smooth = 0,
            build_construction = 0, set_standing_order = 0,
            set_dig_priority = 0, apply_template = 0, build_room = 0,
            ensure_furniture = 0,
            build_workshop_cluster = 0 }

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
-- Say why, once, in the shape the rest of the file already uses. Nine of the twenty-four
-- verbs measured in the coverage audit returned zero with no counter and no reason: a
-- failed precondition simply fell out of the pcall and the caller saw a successful apply
-- with nothing in it. A verb that declines must name the condition it could not meet.
local function refuse(verb, why)
    print(string.format('REFUSED %s: %s', verb, tostring(why)))
end

-- A verb that hit an obstacle and worked around it did NOT refuse, and must not say so.
-- designate_dig printed `REFUSED designate_dig: ... damp stone ...` on every call while
-- going on to designate 12-14 tiles that round, so the one channel the agent learns
-- outcomes from reported failure for an action that had succeeded. Refusal means nothing
-- happened; anything else is a note.
local function note(verb, what)
    print(string.format('NOTE %s: %s', verb, tostring(what)))
end

-- Both labour verbs took a name and silently did nothing when DF had no such labour.
-- Measured by driving every verb through the gate with a deliberately wrong argument:
-- set_labor and set_dwarf_labor were the ONLY two of twenty-five that returned zero with
-- nothing said, while set_standing_order answered the same nonsense with "DF has no
-- standing order named best; it has 50, for example auto_butcher, ...". The labour
-- argument carries no `choices` in the schema either, so a controller has to guess the
-- name from a doc string -- it WILL get one wrong, and a silent zero teaches it nothing.
local function labor_id(name)
    local lid = df.unit_labor[name or ""]
    if lid then return lid end
    local known = {}
    pcall(function()
        for i = df.unit_labor._first_item, df.unit_labor._last_item do
            local k = df.unit_labor[i]
            if type(k) == "string" and k ~= "NONE" then known[#known + 1] = k end
        end
    end)
    table.sort(known)
    local sample = {}
    for i = 1, math.min(3, #known) do sample[i] = known[i] end
    return nil, string.format("DF has no labour named %s; it has %d, for example %s",
                              tostring(name), #known, table.concat(sample, ", "))
end

-- Every verb body runs inside pcall and the error was thrown away, so a failure
-- in the BODY looked exactly like a verb that chose to do nothing: zero counter,
-- no refusal, no trace. set_standing_order passed both of its preconditions and
-- still reported nothing, because the assignment underneath raised and vanished.
-- Keep the isolation - one bad verb must not abort the batch - but say what broke.
local function attempt(verb, fn)
    local ok, err = pcall(fn)
    if not ok then refuse(verb, err) end
    return ok
end

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
                    -- broad, so ask who holds the item instead.
                    --
                    -- The wagon is NOT the exception it was written as. Counting its
                    -- contents as stock is right — the fort does own its embark supplies
                    -- — but handing one to a construction job is not: DF refuses it while
                    -- it is still the parent civilisation's property, and it refuses it
                    -- by cancelling the job and DELETING the building, after the verb has
                    -- already reported success. Measured on ourfort16-final, where the
                    -- only wood was the three logs in the wagon:
                    --     Construct building: Needs building material non-economic item.
                    --     The dwarves were unable to complete the Carpenter's Workshop.
                    -- and world.buildings.all held no workshop at all a few hundred ticks
                    -- later. Once trees were felled and eight logs lay on the ground, the
                    -- identical call built and kept its workshop.
                    --
                    -- So: reachable-for-stock and usable-as-a-reagent are two questions,
                    -- and this one wants the second. Returning nil lets the verb refuse
                    -- with a reason instead of building something DF will silently drop.
                    local in_wagon = false
                    if reach then
                        pcall(function() in_wagon = reach.in_wagon(it) end)
                    else
                        pcall(function()
                            local h = dfhack.items.getHolderBuilding(it)
                            in_wagon = h ~= nil and h:getType() == df.building_type.Wagon
                        end)
                    end
                    if not in_wagon then
                        local holder = nil
                        pcall(function() holder = dfhack.items.getHolderBuilding(it) end)
                        if not holder then return it end
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
    -- A noble's room needs an armour stand, a weapon rack and often a statue, and none of
    -- them could be ordered: a baron's bedroom was designable and unfurnishable. The job
    -- names were checked against df.job_type rather than written from memory —
    -- ConstructArmorStand=76, ConstructWeaponRack=77, ConstructStatue=79 all exist, while
    -- MakeArmorStand, MakeWeaponRack and MakeStatue do not.
    ConstructArmorStand = { { mat = 'wood',  shop = 'Carpenters', item = 'WOOD' },
                            { mat = 'stone', shop = 'Masons',     item = 'BOULDER' } },
    ConstructWeaponRack = { { mat = 'wood',  shop = 'Carpenters', item = 'WOOD' },
                            { mat = 'stone', shop = 'Masons',     item = 'BOULDER' } },
    ConstructStatue     = { { mat = 'stone', shop = 'Masons',     item = 'BOULDER' } },
}

-- What a design's furniture is called, on both sides: the job that makes it and the item
-- that results. Used to raise the orders a build request implies, and to count what the
-- fort already has so it does not order twice.
local PIECE_JOB = {
    b = { job = 'ConstructBed',        item = 'BED' },
    c = { job = 'ConstructThrone',     item = 'CHAIR' },
    t = { job = 'ConstructTable',      item = 'TABLE' },
    f = { job = 'ConstructCabinet',    item = 'CABINET' },
    h = { job = 'ConstructChest',      item = 'BOX' },
    n = { job = 'ConstructCoffin',     item = 'COFFIN' },
    d = { job = 'ConstructDoor',       item = 'DOOR' },
    a = { job = 'ConstructArmorStand', item = 'ARMORSTAND' },
    r = { job = 'ConstructWeaponRack', item = 'WEAPONRACK' },
    s = { job = 'ConstructStatue',     item = 'STATUE' },
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

-- A resolved request is one intent, but its leaves are asynchronous game work. Chopping
-- and mining finish several hundred frames after this script returns; a planned workshop
-- finishes later still. Keep visiting the durable order ledger until those prerequisites
-- exist. The flag prevents repeated agent dispatches from installing duplicate pumps.
local function repair_pending_shaft()
    local place = _G.BONSAI_PLACE
    local origin = place and place.dig
    if not origin then return end
    for dz = 0, 10 do
        local x, y, z = origin[1], origin[2], origin[3] - dz
        local tt = dfhack.maps.getTileType(x, y, z)
        local shape = tt and df.tiletype.attrs[tt].shape
        local des = dfhack.maps.getTileFlags(x, y, z)
        -- DF cancels the newly exposed damp/unsafe next stair and clears only that
        -- designation, leaving the still-designated levels below unreachable. This is
        -- the player's second click after the warning, made explicit and idempotent.
        local diggable = shape == df.tiletype_shape.WALL
            or (dz == 0 and shape == df.tiletype_shape.FLOOR)
        if diggable and des
            and des.dig == df.tile_dig_designation.No then
            des.dig = dz == 0 and df.tile_dig_designation.DownStair
                or df.tile_dig_designation.UpDownStair
            local block = dfhack.maps.getTileBlock(x, y, z)
            if block then block.flags.designated = true end
        end
    end
end

local function ensure_order_pump()
    -- Export one idempotent visit so the episode runner can drive it from its proven
    -- heartbeat. Timeouts installed by a short dfhack-run action RPC have been observed
    -- to remain marked active without ever firing; bonsai-run's heartbeat does fire.
    _G.BONSAI_ORDER_PUMP_TICK = function()
        _G.BONSAI_ORDER_PUMP_VISITS = (_G.BONSAI_ORDER_PUMP_VISITS or 0) + 1
        if #_G.BONSAI_ORDERS == 0 then
            _G.BONSAI_ORDER_PUMP_ACTIVE = false
            _G.BONSAI_ORDER_PUMP_LAST_MADE = 0
            return 0
        end
        repair_pending_shaft()
        pcall(function() df.global.process_dig = true end)
        pcall(function() df.global.process_jobs = true end)
        local made = dispatch_orders()
        _G.BONSAI_ORDER_PUMP_LAST_MADE = made
        save_ledger()
        return made
    end
    if #_G.BONSAI_ORDERS == 0 then return end
    -- A map reload does not restart DFHack's Lua process. The old boolean can therefore
    -- survive while its timeout belongs to the unloaded map, leaving a permanently
    -- "active" pump that never ticks. Every invocation takes ownership with a new
    -- generation; older callbacks see that they have been superseded and retire.
    local generation = (_G.BONSAI_ORDER_PUMP_GENERATION or 0) + 1
    _G.BONSAI_ORDER_PUMP_GENERATION = generation
    _G.BONSAI_ORDER_PUMP_ACTIVE = true
    _G.BONSAI_ORDER_PUMP_ERROR = nil
    local function tick()
        if _G.BONSAI_ORDER_PUMP_GENERATION ~= generation then return end
        local ok, err = pcall(_G.BONSAI_ORDER_PUMP_TICK)
        if ok and #_G.BONSAI_ORDERS > 0 then
            dfhack.timeout(300, 'frames', tick)
        else
            if not ok then
                _G.BONSAI_ORDER_PUMP_ERROR = tostring(err)
                dfhack.printerr('bonsai order pump stopped: ' .. tostring(err))
            end
            _G.BONSAI_ORDER_PUMP_ACTIVE = false
        end
    end
    dfhack.timeout(1, 'frames', tick)
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
    if who and who ~= '' and who ~= 'best' and who ~= 'any' then
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
            -- `a and b or c` is not an if/else when b can be FALSE: a reach test that
            -- answers "no" collapses the and-chain and hands the decision to the flag
            -- list, which then accepts an item nobody can walk to. The flags are the
            -- fallback for when the reach module is ABSENT, not a second opinion when it
            -- says no. free_material a few hundred lines up already spells this out.
            local usable
            if reach then
                usable = reach.item(it, REACH_GROUPS)
            else
                usable = not (it.flags.forbid or it.flags.in_job or it.flags.removed
                              or it.flags.foreign)
            end
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

-- Can the fort actually satisfy this build requirement, right now?
--
-- DF will happily let you PLACE a Quern with no quern in the fort; the job simply waits
-- forever. A player can see that and undo it. Our agent cannot: `build_workshop` would
-- report success, the building would be counted by every observer that counts buildings,
-- and nothing would ever stand there. So the verb asks first.
--
-- `f.flags2.fire_safe` cannot be evaluated exactly here — that needs the material's melt
-- point — so this uses the one rule that is certainly true and certainly relevant on an
-- early fort: WOOD BURNS. A furnace asking for fire-safe material will not accept a log,
-- and refusing on that is conservative in the direction that matters.
local function can_supply(f, groups)
    local want_type = -1
    pcall(function() want_type = f.item_type or -1 end)
    local qty = 1
    pcall(function() qty = math.max(1, f.quantity or 1) end)
    local need_fire, need_magma, need_empty = false, false, false
    pcall(function()
        need_fire = f.flags2 and f.flags2.fire_safe or false
        need_magma = f.flags2 and f.flags2.magma_safe or false
        need_empty = f.flags1 and f.flags1.empty or false
    end)
    local found = 0
    for _, it in ipairs(w.items.all) do
        local t = it:getType()
        local match
        if want_type >= 0 then
            match = (t == want_type)
        else
            -- "any building material": what an early fort actually has
            match = (t == df.item_type.WOOD or t == df.item_type.BOULDER
                     or t == df.item_type.BLOCKS or t == df.item_type.BAR)
        end
        if match and (need_fire or need_magma) and t == df.item_type.WOOD then
            match = false                        -- wood burns
        end
        if match and need_empty then
            local n = 0
            pcall(function() n = #dfhack.items.getContainedItems(it) end)
            if n > 0 then match = false end
        end
        -- Same distinction free_material draws: an item still inside the embark wagon
        -- counts as the fort's stock but DF will not accept it as a building material
        -- while it remains the parent civilisation's property. Counting it here made
        -- build_workshop believe it had wood, place the building, and lose it to
        -- "Needs building material non-economic item" a few hundred ticks later.
        if match and reach then
            local wag = false
            pcall(function() wag = reach.in_wagon(it) end)
            if wag then match = false end
        end
        if match and (not reach or reach.item(it, groups)) then
            found = found + 1
            if found >= qty then return true, found end
        end
    end
    return false, found
end

-- Send a dwarf to a workshop, the way a player does on its Workers tab.
--
-- The owner asked for this — "когда мы можем посылать рабочих" — and it is a normal
-- mechanic. `building.profile.permitted_workers` is what DF's own Workers tab edits,
-- proved causally rather than by reading the field back: two identical Carpenters
-- workshops restricted to different dwarves, then the assignment SWAPPED, and the working
-- dwarf swapped with it three times out of three while other capable dwarves declined.
--
-- Three things that are easy to get wrong and each silent:
--
--   * The vector must be written with `utils.insert_sorted`, NOT `insert('#', id)`.
--     DF itself scans it linearly and honours an unsorted list, but DFHack's binsearch
--     then returns FALSE for an id that is physically in the vector — so our own
--     read-back would deny an assignment that is really there.
--   * There is NO back-reference. `df.unit` has only `owned_buildings`, which is rooms.
--     Here the one-sided link is correct by design, which is worth stating because in
--     this project it is normally the bug.
--   * A permitted worker who lacks the LABOUR makes the job sit forever with no
--     announcement at all — measured at 2,760 frames of WORKER=none, then one labour bit
--     flipped and the same dwarf took it within 540. So `#permitted_workers > 0` is a
--     worthless assertion, and this refuses rather than creating that silence.
--
-- `min_level`/`max_level` go inert once a master is named — DF hides the skill slider —
-- so they are left alone.
local function assign_worker(b, unit)
    if not (b and unit) then return false, 'no building or unit' end
    local prof
    if not pcall(function() prof = b.profile end) or not prof then
        return false, 'building has no profile'
    end
    if not pcall(function() return #prof.permitted_workers end) then
        return false, 'profile has no permitted_workers'
    end
    -- NO build-stage guard. A master name sticks on a workshop at stage 0/3 and DFHack's
    -- binsearch finds it — measured on a freshly placed Carpenters. Refusing until the
    -- building is finished made a cluster structurally unable to staff itself, since
    -- every shop it places is unbuilt at that moment. That guard came from reasoning
    -- about what ought to be true rather than from asking.
    --
    -- The LABOUR guard below is different: it is measured, and it is the one that matters.

    -- Traps carry a profile too — building_trapst has `permitted_workers` — so gating on
    -- the field alone would quietly accept a lever. Decide it rather than inherit it.
    if b:getType() == df.building_type.Trap then
        return false, 'a trap is not a workshop; assign its puller some other way'
    end

    -- AND IT MUST FAIL CLOSED. `get_profile_labors` is a hardcoded 16-entry UI table, not
    -- a labour oracle: measured live, it returns {} for 17 of the 33 profile-bearing
    -- subtypes — Mechanics, Kitchen, Loom, Tanners, Clothiers, Dyers, Bowyers, Siege,
    -- Leatherworks, Kennels, Tool, and every furnace but two. Reading an empty list as
    -- "no requirement" meant that for exactly those seventeen this guard would have
    -- created the 2,760-frame silent stall it exists to prevent.
    local labors = {}
    pcall(function()
        labors = require('plugins.orders').get_profile_labors(b:getType(), b:getSubtype())
                 or {}
    end)
    if #labors == 0 then
        return false, 'no labour list for this building kind, so a master would stall it'
    end
    local can = false
    for _, name in ipairs(labors) do
        local id = df.unit_labor[name]
        if id and unit.status.labors[id] then can = true end
    end
    if not can then return false, 'the dwarf has none of this shop\'s labours' end

    local okw = pcall(function()
        -- one master per shop, the way DF's own Workers tab holds it
        prof.permitted_workers:resize(0)
        require('utils').insert_sorted(prof.permitted_workers, unit.id)
    end)
    if not okw then return false, 'the write failed' end
    local back = false
    pcall(function()
        for _, id in ipairs(prof.permitted_workers) do
            if id == unit.id then back = true end
        end
    end)
    return back, back and '' or 'the id did not stick'
end

-- Somebody who can actually work here, preferring whoever is not already master of
-- another shop so a cluster does not hand every building to the same dwarf.
local function worker_for(b, taken)
    local labors = {}
    pcall(function()
        labors = require('plugins.orders').get_profile_labors(b:getType(), b:getSubtype())
                 or {}
    end)
    if #labors == 0 then return nil end        -- fail closed, same as assign_worker
    local fallback
    for _, u in ipairs(cits) do
        local can = false
        for _, name in ipairs(labors) do
            local id = df.unit_labor[name]
            if id and u.status.labors[id] then can = true end
        end
        if can then
            if not (taken and taken[u.id]) then return u end
            fallback = fallback or u
        end
    end
    return fallback
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
-- Where the fort can actually put a pick to rock: every tile a citizen can STAND on,
-- deepest first. Not "where a dwarf happens to be standing".
--
-- This exists because of a fort that spent 55,000 frames not digging. Rendered, it was a
-- surface camp on a meadow at z=49 with one 11x5 chamber below it at z=48, and every
-- anchor the search offered was a citizen's own z — the surface. So it proposed rooms in
-- the unexplored cliff face twenty tiles away, `dig_site` was satisfied by neighbours
-- ABOVE and BELOW the rock, and DF quietly made no job at all: not one of the 29
-- designated tiles had a walkable tile beside it on its own level, and a miner cuts a
-- wall from the side. No announcement, because there was no work to cancel.
--
-- Deepest-first because that is where rooms belong, and because the chamber at the bottom
-- of the shaft is the frontier a player would dig from.
local function fort_anchors(limit)
    if not reach then return {} end
    local cx, cy, n = 0, 0, 0
    local zlo, zhi
    for _, u in ipairs(cits) do
        cx, cy, n = cx + u.pos.x, cy + u.pos.y, n + 1
        zlo = math.min(zlo or u.pos.z, u.pos.z)
        zhi = math.max(zhi or u.pos.z, u.pos.z)
    end
    if n == 0 then return {} end
    cx, cy = cx / n, cy / n
    -- Bounded in z as well as x/y: unbounded, this walks every block on a 66-level map and
    -- asks the pathfinder about half a million tiles.
    zlo, zhi = zlo - 16, zhi + 2
    local out = {}
    for _, blk in ipairs(df.global.world.map.map_blocks) do
        local bx, by, bz = blk.map_pos.x, blk.map_pos.y, blk.map_pos.z
        -- a block 48+ tiles out is not a frontier we would dig from
        if bz >= zlo and bz <= zhi
           and math.abs(bx - cx) <= 48 and math.abs(by - cy) <= 48 then
            for lx = 0, 15 do
                for ly = 0, 15 do
                    local x, y = bx + lx, by + ly
                    if reach.tile(x, y, bz, REACH_GROUPS) then
                        out[#out + 1] = { x, y, bz,
                            (x - cx) * (x - cx) + (y - cy) * (y - cy) }
                    end
                end
            end
        end
    end
    table.sort(out, function(a, b)
        if a[3] ~= b[3] then return a[3] < b[3] end   -- deeper first
        return a[4] < b[4]                            -- then nearest the fort
    end)
    if limit and #out > limit then
        local cut = {}
        for i = 1, limit do cut[i] = out[i] end
        return cut
    end
    return out
end

local function find_site(bw, bh, radius, cursor, tries, for_digging, hard_only,
                         entry_x, entry_y)
    local function fits(x, y, z)
        if not reach then return true end
        if for_digging then
            return (reach.dig_site(x, y, z, bw, bh, REACH_GROUPS, hard_only,
                                   entry_x, entry_y))
        end
        return (reach.site(x, y, z, bw, bh, REACH_GROUPS))
    end
    -- Digging is sited off the fort's own frontier BEFORE the tidy ring is tried: the ring
    -- samples an annulus around the fort centre with no regard for whether a miner can
    -- stand there, and on a shallow fort every one of its samples is open surface.
    if for_digging then
        for _, a in ipairs(fort_anchors(4000)) do
            local ax, ay, az = a[1], a[2], a[3]
            -- lay the box against this tile on each side, so its edge touches ground a
            -- miner already stands on. dig_site then judges the rest.
            local tries_here
            if entry_x ~= nil and entry_y ~= nil then
                -- Put the blueprint's ACTUAL opening, not merely an arbitrary wall in
                -- its bounding box, beside this reachable anchor.
                tries_here = {
                    { ax + 1 - entry_x, ay - entry_y },
                    { ax - 1 - entry_x, ay - entry_y },
                    { ax - entry_x, ay + 1 - entry_y },
                    { ax - entry_x, ay - 1 - entry_y },
                }
            else
                tries_here = {
                    { ax + 1, ay }, { ax - bw, ay }, { ax, ay + 1 }, { ax, ay - bh },
                    { ax + 1, ay - bh + 1 }, { ax - bw, ay - bh + 1 },
                    { ax - bw + 1, ay + 1 }, { ax - bw + 1, ay - bh },
                }
            end
            for _, t in ipairs(tries_here) do
                if fits(t[1], t[2], az) then return t[1], t[2], az end
            end
        end
    end
    for i = 0, (tries or 48) - 1 do
        local x, y, z = site((cursor or 0) + i, radius or 6)
        if x and fits(x, y, z) then return x, y, z end
    end
    if not u1 then return nil end
    -- Every z-level the fort demonstrably lives on, nearest-first from each anchor.
    --
    -- The fallback used to scan only `u1.pos.z`, which is wherever the FIRST citizen
    -- happens to be standing. On a fort with a deep shaft that is a one-tile corridor,
    -- and the verb would report "no room" with the whole surface empty above it —
    -- measured: build_workshop, create_stockpile and create_zone all refused while
    -- apply_template was stamping designs two z-levels up. Anchoring on every level a
    -- citizen stands on, plus the shaft head, uses what the fort is actually doing
    -- rather than one dwarf's accident.
    local anchors, seen = {}, {}
    for _, u in ipairs(cits) do
        local key = u.pos.z
        if not seen[key] then
            seen[key] = true
            anchors[#anchors + 1] = { u.pos.x, u.pos.y, u.pos.z }
        end
    end
    if P and P.dig and not seen[P.dig[3]] then
        anchors[#anchors + 1] = { P.dig[1], P.dig[2], P.dig[3] }
    end
    for _, a in ipairs(anchors) do
        for r = 2, 30 do
            for dx = -r, r do
                for dy = -r, r do
                    -- only the ring's edge, so the scan grows outward instead of
                    -- re-testing ground it has already refused
                    if math.abs(dx) == r or math.abs(dy) == r then
                        local x, y, z = a[1] + dx, a[2] + dy, a[3]
                        if fits(x, y, z) then return x, y, z end
                    end
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
-- Returns x, y, z, crop_id — or nils plus a REASON. A silent nil here used to mean the
-- fort simply never got a farm and nobody could say why, which on a fresh embark is the
-- normal case rather than a rare one.
local function farm_site(pw, ph, want_plant)
    if not u1 then return nil, nil, nil, nil, 'no citizen to search around' end

    local candidates = {}
    if want_plant and want_plant ~= '' and want_plant ~= 'best' then
        local idx, p = plant_index(want_plant)
        if not idx then
            return nil, nil, nil, nil, 'no such crop: ' .. tostring(want_plant)
        end
        candidates[1] = { id = want_plant, under = subterranean(p) }
    else
        candidates = crops_by_preference()
    end
    if #candidates == 0 then
        return nil, nil, nil, nil, 'no seeds the fort can reach'
    end

    -- This search hung DF outright on a fresh embark - fifteen minutes without finishing
    -- one round, the game deaf to RPC. Three compounding costs, and the fresh fort hits
    -- the worst case every time: most dwarven crops are subterranean, an undug surface
    -- embark has no indoor soil at all, so nothing ever matches and the whole space is
    -- always exhausted. The mature fort finds a plot immediately and never showed it.
    --
    --   1. `r` re-scanned the entire square from -r to r at every radius, so radius 30
    --      re-tested everything it had already rejected twenty-nine times. It walks the
    --      ring now: sum (2r+1)^2 = ~37800 positions becomes sum 8r = ~3700.
    --   2. Overlapping candidate rectangles asked about the same tile up to pw*ph times,
    --      and plantable() is three or four DFHack round trips each (getTileType,
    --      findAtTile, reach.tile, sometimes getTileFlags). Memoised per tile.
    --   3. Every crop restarted the whole scan. Crops differ only in `under`, so the
    --      cache collapses that to two passes however many crops there are - which keeps
    --      crop-preference order intact rather than trading it for proximity.
    --
    -- The budget is the part that matters most: it is a hard ceiling on tile queries, so
    -- no map can ever hang the game here again. A full legitimate search over 11 levels
    -- costs about 92000 lookups, so the default leaves real headroom before refusing.
    local budget = tonumber(os.getenv('BONSAI_FARM_SITE_BUDGET') or '') or 120000
    local cache, exhausted, queried = {}, false, 0
    local function tile_ok(x, y, z, indoors)
        local key = (indoors and 'i' or 'o') .. x .. ',' .. y .. ',' .. z
        local hit = cache[key]
        if hit == nil then
            if budget <= 0 then exhausted = true; return false end
            budget, queried = budget - 1, queried + 1
            hit = plantable(x, y, z, indoors)
            cache[key] = hit
        end
        return hit
    end
    local function fits(x0, y0, z, indoors)
        for x = x0, x0 + pw - 1 do
            for y = y0, y0 + ph - 1 do
                if not tile_ok(x, y, z, indoors) then return false end
            end
        end
        return true
    end

    for _, crop in ipairs(candidates) do
        for dz = 0, -10, -1 do
            local z = u1.pos.z + dz
            for r = 0, 30 do
                for dx = -r, r do
                    for dy = -r, r do
                        if r == 0 or math.abs(dx) == r or math.abs(dy) == r then
                            local x0, y0 = u1.pos.x + dx, u1.pos.y + dy
                            if fits(x0, y0, z, crop.under) then
                                return x0, y0, z, crop.id
                            end
                        end
                        if exhausted then
                            return nil, nil, nil, nil, string.format(
                                'search budget exhausted after %d tile lookups', queried)
                        end
                    end
                end
            end
        end
    end
    return nil, nil, nil, nil, string.format(
        '%d crop(s), %d tiles checked, no %dx%d plantable site within 30 tiles across 11 levels',
        #candidates, queried, pw, ph)
end


-- ============================================================ requirement resolution
--
-- The owner's requirement, in his words:
--     вся эта цепочка из требований должна раскрываться и автоматически резолвится
--
-- "Place an office" is not one action. It is: a chair and a table and a door — three items
-- nobody has made — which need a Carpenter's workshop, which needs a log, which needs a
-- tree felled. Hand-running that chain proves the mechanics and is exactly what a player
-- never has to do: DF's own build menu will not let you place a bed that does not exist,
-- so the REQUEST is what has to unfold.
--
-- A request therefore expands into its own prerequisites and they run in the SAME call.
-- The dispatcher below is a queue rather than a file scan, and `need()` splices the missing
-- step in AHEAD of whatever is still pending, so the chain executes in dependency order.
--
-- Recursion terminates at the two things the world provides directly: trees (chop_trees)
-- and rock (designate_dig). Everything else is a workshop plus a reagent.

local QUEUE, QI = {}, 1
if mode ~= 'pump' then
    for line in f:lines() do QUEUE[#QUEUE + 1] = line end
end
f:close()

-- Splice a prerequisite in so it runs next, before the rest of the request.
--
-- The cursor matters. Inserting every prerequisite at the same index reverses them —
-- the last one asked for ends up first — and the chain would try to build a workshop
-- before there is a log to build it from. So each splice lands after the previous one,
-- and the cursor resets to the current line at the top of every dispatch.
local NEED_AT = 1
local function need(line)
    table.insert(QUEUE, NEED_AT, line)
    NEED_AT = NEED_AT + 1
end

-- Asked for already, in this call. Without this a design wanting a chair AND a table
-- orders two carpenters' workshops and fells the forest twice.
local RESOLVED = {}
local RESOLVE_LOG = {}

local function free_items(item_name)
    local it = df.item_type[item_name]
    if it == nil then return 0 end
    local n = 0
    for _, i in ipairs(w.items.all) do
        if i:getType() == it and not (i.flags.in_job or i.flags.forbid or i.flags.foreign
            or i.flags.removed or i.flags.in_building) then
            n = n + 1
        end
    end
    return n
end

local function shop_is_built(shop)
    local want = df.workshop_type[shop]
    if want == nil then return false end
    for _, b in ipairs(w.buildings.all) do
        if df.building_workshopst:is_instance(b) and b.type == want and built(b) then
            return true
        end
    end
    return false
end

-- Raw material the world hands out directly. `n` is how many we are short.
local function ensure_material(item_name, n)
    if free_items(item_name) >= n then return true end
    local key = 'mat:' .. item_name
    if RESOLVED[key] then return true end       -- already asked this call
    RESOLVED[key] = true
    if item_name == 'WOOD' then
        -- felling yields one log per tree, and a tree is not always reachable, so ask for
        -- comfortably more than the shortfall rather than exactly it
        need(string.format('chop_trees\t%d', math.max(8, n * 3)))
        RESOLVE_LOG[#RESOLVE_LOG + 1] = 'chop trees for ' .. n .. ' wood'
        return true
    elseif item_name == 'BOULDER' then
        -- The first walls below an embark are often soil and stone drops are not
        -- guaranteed per mined rock tile. Three designations produced exactly enough
        -- building material for the workshop and zero free boulders on the clean test
        -- fort, leaving its statue order permanently armed. Dig through the soil cap
        -- and expose a small chamber so both the workshop and its products are supplied.
        need(string.format('designate_dig\t%d', math.max(30, n * 12)))
        RESOLVE_LOG[#RESOLVE_LOG + 1] = 'dig for ' .. n .. ' stone'
        return true
    end
    return false                                 -- nothing in the world makes this
end

local function ensure_shop(shop)
    if shop_is_built(shop) then return true end
    local key = 'shop:' .. shop
    if RESOLVED[key] then return true end
    RESOLVED[key] = true
    -- the shop itself is built OUT OF something; the stone shops out of stone, the rest
    -- out of whatever `getFiltersByType` says, which for the common ones is a log
    local mat = (shop == 'Masons' or shop == 'Mechanics') and 'BOULDER' or 'WOOD'
    ensure_material(mat, 1)
    -- Raw materials arrive asynchronously: a tree has to fall and a wall has to be
    -- mined before either item exists. Mark resolver-created workshops as deferred so
    -- build_workshop registers a real buildingplan plan instead of refusing before the
    -- preceding designation has had time to produce its reagent.
    need('build_workshop\t' .. shop .. '\tdeferred')
    RESOLVE_LOG[#RESOLVE_LOG + 1] = 'build a ' .. shop
    return true
end

-- The whole point: turn "I want N of this piece" into every step that produces it.
local function resolve_piece(key, want)
    local pj = PIECE_JOB[key]
    if not pj then return end
    local have = free_items(pj.item)
    local short = want - have
    if short <= 0 then return end

    -- Pick the variant to make it from. Prefer one whose workshop already stands AND whose
    -- reagent is in the fort — that is the branch that costs nothing. Otherwise take the
    -- first variant and build down to it.
    local variants = JOB_SPEC[pj.job] or {}
    local chosen, cheapest
    for _, v in ipairs(variants) do
        if shop_is_built(v.shop) and free_items(v.item) >= short then chosen = v break end
        if not cheapest and shop_is_built(v.shop) then cheapest = v end
    end
    chosen = chosen or cheapest or variants[1]
    if not chosen then return end

    ensure_material(chosen.item, short)
    ensure_shop(chosen.shop)
    need(string.format('add_workorder\t%s\t%d\t%s', pj.job, short, chosen.mat))
    RESOLVE_LOG[#RESOLVE_LOG + 1] = string.format('%s x%d from %s at the %s',
        pj.job, short, chosen.mat, chosen.shop)
end

-- `c:1,d:1,t:1` -> every action that ends with those three items existing.
local function resolve_pieces(spec)
    for entry in tostring(spec or ''):gmatch('[^,]+') do
        local key, want = entry:match('^(%a):(%d+)$')
        if key and want then resolve_piece(key, tonumber(want)) end
    end
end

-- A constructed surface room pays for a real shell. Prefer blocks: one masonry job turns
-- one boulder into four building pieces, so a 70-tile shell does not clear-cut seventy
-- trees. buildingplan holds the construction intents while this dependency chain runs.
local function resolve_building_materials(want)
    local short = math.max(0, (tonumber(want) or 0) - free_items('BLOCKS'))
    if short <= 0 then return end
    local jobs = math.max(1, math.ceil(short / 4))
    ensure_material('BOULDER', jobs + 1) -- one extra boulder pays for the Mason's itself
    ensure_shop('Masons')
    need(string.format('add_workorder\tConstructBlocks\t%d\tstone', jobs))
    RESOLVE_LOG[#RESOLVE_LOG + 1] = string.format(
        'make about %d blocks for %d remaining construction tiles', jobs * 4, short)
end

-- ============================================================ durable room workflow
--
-- apply_template is intentionally atomic and low-level. build_room is the player-sized
-- request above it: choose a legal site, wait for excavation or a constructed shell,
-- furnish, create exactly one zone, assign an owner, and prove the result. The record is
-- site data, not a Lua global, so a save/load or a dead RPC client resumes the same room.
local ROOM_KEY = 'bonsai/room-workflows-v1'
local function load_rooms()
    local ok, rows = pcall(dfhack.persistent.getSiteData, ROOM_KEY)
    return ok and type(rows) == 'table' and rows or {}
end
local ROOMS = load_rooms()
local function save_rooms()
    pcall(dfhack.persistent.saveSiteData, ROOM_KEY, ROOMS)
end

local PIECE_BUILDING = {
    a = df.building_type.Armorstand, b = df.building_type.Bed,
    c = df.building_type.Chair, d = df.building_type.Door,
    f = df.building_type.Cabinet, h = df.building_type.Box,
    n = df.building_type.Coffin, r = df.building_type.Weaponrack,
    s = df.building_type.Statue, t = df.building_type.Table,
}

local function parse_counts(spec)
    local out = {}
    for entry in tostring(spec or ''):gmatch('[^,]+') do
        local key, n = entry:match('^(%a):(%d+)$')
        if key and n then out[key] = tonumber(n) end
    end
    return out
end

local function in_room_box(b, r)
    return b.z == r.z and b.x1 >= r.x and b.x1 < r.x + r.w
        and b.y1 >= r.y and b.y1 < r.y + r.h
end

local function built_piece_counts(r)
    local out = {}
    for _, b in ipairs(w.buildings.all) do
        if in_room_box(b, r) and built(b) then
            local bt = b:getType()
            for key, want in pairs(PIECE_BUILDING) do
                if bt == want then out[key] = (out[key] or 0) + 1 end
            end
        end
    end
    return out
end

local function missing_piece_spec(r)
    local want, have, out = parse_counts(r.furniture), built_piece_counts(r), {}
    for key, n in pairs(want) do
        local short = math.max(0, n - (have[key] or 0))
        if short > 0 then out[#out + 1] = key .. ':' .. short end
    end
    table.sort(out)
    return table.concat(out, ',')
end

local function room_zones(r)
    local out = {}
    local subtype = df.civzone_type[r.kind]
    local x, y = r.x + r.zx, r.y + r.zy
    for _, b in ipairs(w.buildings.all) do
        if b:getType() == df.building_type.Civzone and b:getSubtype() == subtype
            and b.z == r.z and b.x1 == x and b.y1 == y
            and b.x2 == x + r.zw - 1 and b.y2 == y + r.zh - 1 then
            out[#out + 1] = b
        end
    end
    return out
end

local function run_room_label(r, qf, label)
    local cursor = string.format('%d,%d,%d', r.x + r.sx - 1, r.y + r.sy - 1, r.z)
    local ok = pcall(function()
        dfhack.run_command('quickfort', 'run', '-c', cursor, qf, '-n', '/' .. label)
    end)
    return ok
end

local function prioritize_room_dig(r)
    -- A room request is a short dependency chain, not background expansion. On a mature
    -- fort with a hundred queued jobs its doorway otherwise waited indefinitely behind
    -- unrelated mining. DF stores designation priority in a block-square event (the
    -- same representation used by quickfort), not on the designation itself.
    for x = r.x, r.x + r.w - 1 do
        for y = r.y, r.y + r.h - 1 do
            -- Do this for the entire blueprint, including the doorway whose designation
            -- DF has already converted into an unassigned Dig job. The designation on
            -- that square is then No, but its block priority still controls the job.
            -- Filtering on des.dig left exactly the dependency-opening job at priority 4
            -- while the still-hidden interior was priority 1 (measured live on 53.16).
            pcall(function()
                local blk = dfhack.maps.getTileBlock(xyz2pos(x, y, r.z))
                if not blk then return end
                local pbse
                for _, ev in ipairs(blk.block_events) do
                    if ev:getType() == df.block_square_event_type.designation_priority then
                        pbse = ev
                        break
                    end
                end
                if not pbse then
                    blk.block_events:insert('#',
                        { new = df.block_square_event_designation_priorityst })
                    pbse = blk.block_events[#blk.block_events - 1]
                end
                pbse.priority[x % 16][y % 16] = 1000
                blk.flags.designated = true
            end)
        end
    end
end

local function cancel_room_dig_jobs(r)
    local link = w.jobs.list
    while link do
        local next_link, job = link.next, link.item
        if job and job.pos.z == r.z
            and job.pos.x >= r.x and job.pos.x < r.x + r.w
            and job.pos.y >= r.y and job.pos.y < r.y + r.h then
            local name = tostring(df.job_type[job.job_type])
            if name == 'Dig' or name:match('Stair') or name == 'CarveRamp' then
                pcall(dfhack.job.removeJob, job)
            end
        end
        link = next_link
    end
end

local function carved_count(r)
    local n, pending = 0, 0
    for x = r.x, r.x + r.w - 1 do
        for y = r.y, r.y + r.h - 1 do
            local tt = dfhack.maps.getTileType(x, y, r.z)
            if tt then
                local shape = df.tiletype.attrs[tt].shape
                local basic = df.tiletype_shape.attrs[shape].basic_shape
                if basic == df.tiletype_shape_basic.Floor then n = n + 1 end
            end
            local des = dfhack.maps.getTileFlags(x, y, r.z)
            if des and des.dig ~= df.tile_dig_designation.No then pending = pending + 1 end
        end
    end
    return n, pending
end

local function smooth_count(r)
    local n = 0
    for x = r.x, r.x + r.w - 1 do
        for y = r.y, r.y + r.h - 1 do
            local tt = dfhack.maps.getTileType(x, y, r.z)
            if tt and df.tiletype.attrs[tt].special == df.tiletype_special.SMOOTH then
                n = n + 1
            end
        end
    end
    return n
end

local function shell_count(r)
    local walls, floors = 0, 0
    for x = r.x, r.x + r.w - 1 do
        for y = r.y, r.y + r.h - 1 do
            local tt = dfhack.maps.getTileType(x, y, r.z)
            if tt then
                local a = df.tiletype.attrs[tt]
                if a.material == df.tiletype_material.CONSTRUCTION then
                    if a.shape == df.tiletype_shape.WALL then walls = walls + 1 end
                    if a.shape == df.tiletype_shape.FLOOR then floors = floors + 1 end
                end
            end
        end
    end
    return walls, floors
end

local function room_owner(r)
    if r.owner == 'role' then
        local code = tostring(r.position):upper():gsub('[^A-Z0-9]+', '_')
        local ok, unit = pcall(dfhack.units.getUnitByNobleRole, code)
        return ok and unit or nil
    end
    return pick_citizen(r.owner, r.owner == 'any' or r.owner == '')
end

local function room_reachable(r)
    if not reach then return true end
    for x = r.x + r.zx, r.x + r.zx + r.zw - 1 do
        for y = r.y + r.zy, r.y + r.zy + r.zh - 1 do
            if reach.tile(x, y, r.z, REACH_GROUPS) then return true end
        end
    end
    return false
end

local function finish_receipt(r)
    local zones = room_zones(r)
    if #zones > 1 then
        r.state, r.reason = 'error', 'duplicate-zone'
        return false
    end
    if #zones == 0 then return false end
    local zone = zones[1]
    local missing = missing_piece_spec(r)
    if missing ~= '' then r.reason = 'waiting-furniture:' .. missing; return false end
    local unit = room_owner(r)
    if not unit then r.reason = 'waiting-owner:' .. tostring(r.owner); return false end
    if zone.assigned_unit_id ~= unit.id and not own_room(zone, unit) then
        r.reason = 'owner-link-failed'; return false
    end
    local linked = false
    for _, b in ipairs(unit.owned_buildings) do if b == zone then linked = true end end
    if not linked then r.reason = 'owner-link-missing'; return false end
    if not room_reachable(r) then r.reason = 'room-unreachable'; return false end
    local value = -1
    pcall(function()
        local rv = reqscript('bonsai-roomvalue')
        value = select(1, rv.value_of(zone))
    end)
    if value < r.demand then
        r.reason = string.format('value-shortfall:%d/%d', value, r.demand)
        return false
    end
    r.state, r.reason = 'complete', nil
    r.receipt = { zone_id = zone.id, owner_id = unit.id, value = value,
                  demand = r.demand, x = r.x, y = r.y, z = r.z,
                  strategy = r.strategy }
    return true
end

local function request_room_resources(r, force)
    local frame = w.frame_counter
    if not force and r.last_resources and frame - r.last_resources < 12000 then return end
    if r.strategy == 'surface' then
        local walls, floors = shell_count(r)
        resolve_building_materials(math.max(0, r.walls + r.floors - walls - floors))
    end
    resolve_pieces(missing_piece_spec(r))
    r.last_resources = frame
end

local function ensure_one_zone_and_furniture(r)
    local zones = room_zones(r)
    if #zones > 1 then r.state, r.reason = 'error', 'duplicate-zone'; return false end
    if #zones == 0 then
        if not run_room_label(r, r.strategy == 'surface' and r.surface_qf or r.qf, 'zone') then
            r.reason = 'zone-command-failed'; return false
        end
        zones = room_zones(r)
        if #zones ~= 1 then r.reason = 'zone-not-created'; return false end
    end
    if not r.build_planned or (w.frame_counter - (r.last_build or 0) >= 12000) then
        run_room_label(r, r.strategy == 'surface' and r.surface_qf or r.qf, 'build')
        r.build_planned, r.last_build = true, w.frame_counter
    end
    request_room_resources(r, not r.resources_requested)
    r.resources_requested = true
    r.state = 'furnishing'
    return true
end

local function advance_room(r)
    if r.state == 'complete' or r.state == 'error' then return end
    if not r.x then
        local hard = r.smooth > 0
        local x, y, z
        if r.terrain ~= 'surface' then
            x, y, z = find_site(r.w, r.h, 6, P.tmpl or 0, 48, true, hard,
                                r.door_x, r.door_y)
            if x then r.strategy = 'rock' end
        end
        if not x and r.terrain ~= 'rock' then
            x, y, z = find_site(r.w, r.h, 6, P.tmpl or 0, 48, false)
            if x then r.strategy = 'surface' end
        end
        P.tmpl = (P.tmpl or 0) + 1
        if not x then r.state, r.reason = 'waiting-site', 'no-legal-site'; return end
        r.x, r.y, r.z = x, y, z
        if r.strategy == 'rock' then
            run_room_label(r, r.qf, 'dig')
            prioritize_room_dig(r)
            r.state, r.reason = 'excavating', nil
            pcall(function() df.global.process_dig = true; df.global.process_jobs = true end)
        else
            request_room_resources(r, true)
            run_room_label(r, r.surface_qf, 'shell')
            r.state, r.reason = 'shell', nil
        end
    end

    if r.state == 'excavating' then
        local open, pending = carved_count(r)
        if open < r.dig or pending > 0 then
            prioritize_room_dig(r)
            local sig = string.format('%d:%d', open, pending)
            if r.dig_progress ~= sig then
                r.dig_progress, r.dig_progress_frame = sig, w.frame_counter
            elseif pending > 0 and w.frame_counter - (r.dig_progress_frame or w.frame_counter) >= 12000 then
                -- A legal room must keep making progress. Recover from path/labor state
                -- that DF silently orphaned: remove only designations inside the empty
                -- box this workflow claimed, then choose a newly validated doorway.
                -- Never erase a partially carved player-visible room automatically.
                if open == 0 then
                    cancel_room_dig_jobs(r)
                    for x = r.x, r.x + r.w - 1 do
                        for y = r.y, r.y + r.h - 1 do
                            local des = dfhack.maps.getTileFlags(x, y, r.z)
                            if des then des.dig = df.tile_dig_designation.No end
                        end
                    end
                    r.x, r.y, r.z, r.strategy = nil, nil, nil, nil
                    r.state, r.reason = 'waiting-site', 'relocating-stalled-dig'
                    r.relocations = (r.relocations or 0) + 1
                    r.dig_progress, r.dig_progress_frame = nil, nil
                    return
                end
                r.state, r.reason = 'error', 'partially-dug-room-stalled'
                return
            end
            r.reason = string.format('waiting-dig:%d/%d pending=%d', open, r.dig, pending)
            return
        end
        if r.smooth > 0 then
            run_room_label(r, r.qf, 'smooth')
            r.state, r.reason = 'smoothing', nil
            pcall(function() df.global.process_dig = true end)
        else
            ensure_one_zone_and_furniture(r)
        end
    end
    if r.state == 'smoothing' then
        local done = smooth_count(r)
        if done < r.smooth then
            r.reason = string.format('waiting-smooth:%d/%d', done, r.smooth)
            return
        end
        ensure_one_zone_and_furniture(r)
    end
    if r.state == 'shell' then
        local walls, floors = shell_count(r)
        if walls < r.walls or floors < r.floors then
            r.reason = string.format('waiting-shell:walls=%d/%d floors=%d/%d',
                                     walls, r.walls, floors, r.floors)
            request_room_resources(r, false)
            return
        end
        ensure_one_zone_and_furniture(r)
    end
    if r.state == 'furnishing' then
        if not finish_receipt(r) then request_room_resources(r, false) end
    end
end

local function room_from_args(a)
    local id = a[24]
    local r = ROOMS[id]
    if r then
        if r.qf ~= a[2] then r.state, r.reason = 'error', 'request-id-reused' end
        return r
    end
    r = {
        qf=a[2], surface_qf=a[3], w=tonumber(a[4]), h=tonumber(a[5]),
        sx=tonumber(a[6]), sy=tonumber(a[7]), kind=a[8], position=a[9],
        furniture=a[10], dig=tonumber(a[11]), smooth=tonumber(a[12]),
        walls=tonumber(a[13]), floors=tonumber(a[14]),
        zx=tonumber(a[15]), zy=tonumber(a[16]), zw=tonumber(a[17]), zh=tonumber(a[18]),
        door_x=tonumber(a[19]), door_y=tonumber(a[20]), demand=tonumber(a[21]) or 0,
        terrain=a[22], owner=a[23], request_id=id, state='new', created=w.frame_counter,
    }
    ROOMS[id] = r
    return r
end

-- A pump invocation has no agent actions, but it must revisit every incomplete durable
-- request. Reconstruct the trusted expanded wire form from site data, not from model text.
if mode == 'pump' then
    for _, r in pairs(ROOMS) do
        if r.state ~= 'complete' and r.state ~= 'error' then
            QUEUE[#QUEUE + 1] = table.concat({
                'build_room', r.qf, r.surface_qf, r.w, r.h, r.sx, r.sy, r.kind,
                r.position, r.furniture, r.dig, r.smooth, r.walls, r.floors,
                r.zx, r.zy, r.zw, r.zh, r.door_x, r.door_y, r.demand,
                r.terrain, r.owner, r.request_id,
            }, '\t')
        end
    end
end

while QI <= #QUEUE do
    local line = QUEUE[QI]
    QI = QI + 1
    NEED_AT = QI
    local a = split(line)
    local verb = a[1]
    if verb == "set_labor" then
        attempt("set_labor", function()
            local lid, why = labor_id(a[2])
            if not lid then
                refuse("set_labor", why)
                return
            end
            local on = (a[3] ~= "False" and a[3] ~= "false" and a[3] ~= "0")
            for _, u in ipairs(cits) do u.status.labors[lid] = on end
            c.set_labor = c.set_labor + 1
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
        attempt("designate_dig", function()
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
            -- A tile is damp when water sits in any of the 26 tiles around it. Mining it
            -- is refused by DF and the refusal destroys the designation, so this has to be
            -- caught BEFORE marking rather than discovered as a stall.
            -- The signal is water_table, NOT flow_size. Stone over an aquifer holds no
            -- liquid until it is breached, so a flow_size test reads it as bone dry and
            -- marks it anyway. Measured at the stalled rung, tile 100,91,46: its own
            -- flow_size is 0 and its own water_table is false, while SIXTEEN of its
            -- twenty-six neighbours have water_table true. That is what DF means by
            -- "damp stone located", and checking for liquid instead of for the water
            -- table is why my first attempt at this guard changed nothing.
            local function damp(x, y, z)
                for dx = -1, 1 do
                    for dy = -1, 1 do
                        for dz = -1, 1 do
                            local ok, d = pcall(function()
                                return dfhack.maps.getTileFlags(x + dx, y + dy, z + dz)
                            end)
                            if ok and d and (d.water_table or (d.flow_size or 0) > 0) then
                                return true
                            end
                        end
                    end
                end
                return false
            end
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
                    -- DAMP STONE. DF refuses to mine a tile that touches water and it
                    -- CLEARS the designation when it refuses, so the shaft loses a rung
                    -- and stalls there for good. The game says so in its own words:
                    --   Digging designation cancelled: damp stone located.
                    -- Measured on ourfort16-final: the shaft reached z=47 and z=46 was
                    -- damp, so every re-designation was cancelled again, six of seven
                    -- miners stood idle for 9000 ticks and the fort dug two tiles total.
                    -- The existing guard above only looks at the tile itself; damp is a
                    -- property of its NEIGHBOURS, including diagonals and both z faces.
                    if damp(x, y, z) then return end
                    local tt = dfhack.maps.getTileType(x, y, z)
                    local sh = tt and df.tiletype.attrs[tt].shape
                    -- The shaft head is a down stair cut through a surface FLOOR; all
                    -- lower stairs and ordinary cuts need WALL. Already carved stairs
                    -- match neither, so a retry cannot consume its batch on no-ops.
                    local diggable = sh == df.tiletype_shape.WALL
                        or (kind == DIG.DownStair and sh == df.tiletype_shape.FLOOR)
                    if not diggable then return end
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
            -- shaft: down-stair at the surface, up/down stairs beneath it. STOP at the
            -- first damp rung: everything below it is unreachable until that tile is
            -- mined, and that tile will never be mined, so marking deeper only produces
            -- designations nobody can act on. The fort digs as far as the water allows
            -- and carves its chambers off the deepest landing it actually reached.
            mark(ox, oy, oz, DIG.DownStair)
            local depth, blocked_at = 0, nil
            for dz = 1, 10 do
                if damp(ox, oy, oz - dz) then blocked_at = oz - dz break end
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
            local deferred = 0            -- chambers skipped because a miner cannot reach them yet
            -- Deferring chambers that sit behind undug rock was tried and is OFF. It did
            -- not lift the fresh fort's throughput when asked for too much (30 a call
            -- dug 53 with the gate and 46 without, against 90 when asked for 12), and
            -- it was suspected of collapsing the careful tiers on the mature fort, which
            -- turned out to be the request size instead. Kept switchable because the
            -- reasoning is sound and a fort with slower miners may yet want it.
            local REACH_GATE = false
            -- How far out a chamber may start. Bounded so a saturated fort cannot walk
            -- this to the map edge looking for virgin rock -- but 30 was too tight and it
            -- BOUND. Measured on ourfort16-final: every tier plateaus at 93 dug tiles and
            -- an episode of 12000 ticks scores identically to one of 33600, to six
            -- decimals, because the fort finishes its reachable band and then stands
            -- still for 21600 ticks. The frontier walk already guarantees connectivity --
            -- it starts at the first step that still holds undug wall, and everything
            -- between there and the shaft is designated by definition -- so the bound is
            -- a courtesy against runaway designation, not a correctness condition.
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
                -- Only cut what a miner can WALK TO now. The step before `start` is
                -- either the shaft column or rock that is designated but not yet dug;
                -- a chamber behind undug rock is a job nobody can path to, and DF's
                -- reaction to hundreds of those is not to wait patiently but to churn:
                -- measured on the fresh embark at 3600 ticks, asking 12 tiles a call dug
                -- 91, asking 30 dug 46 and asking 60 dug 49. The miners spent the
                -- episode being assigned unreachable squares and cancelling them. So a
                -- request beyond the walkable frontier is deferred, not refused -- the
                -- caller is told how much is behind rock and to ask again once it is cut.
                if start > 1 then
                    local px, py = at(start - 1, 0, d)
                    local ok, sh = pcall(function()
                        local tt = dfhack.maps.getTileType(px, py, z)
                        return tt and df.tiletype.attrs[tt].shape or nil
                    end)
                    local walkable = ok and (sh == df.tiletype_shape.FLOOR
                        or sh == df.tiletype_shape.STAIR_UP
                        or sh == df.tiletype_shape.STAIR_DOWN
                        or sh == df.tiletype_shape.STAIR_UPDOWN
                        or sh == df.tiletype_shape.RAMP)
                    if not walkable and REACH_GATE then deferred = deferred + 1; return end
                end
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
            -- Spend ordinary wall cuts at the deepest landing first. On a fresh embark
            -- the upper layers are often soil and the staircase itself yields no usable
            -- boulders; walking top-down consumed the whole batch before touching rock.
            --
            -- REFUTED, twice, keep the single level. The obvious next move here is to
            -- cut on every level the fort can walk on rather than only the shaft's
            -- landings: with an aquifer stopping the stair one rung down, `depth` is 1,
            -- so this digs ONE z-level while z=49 and z=50 sit dry and untouched at some
            -- 2100 tiles each. It was built and measured, twice, and lost both times.
            --
            -- Cutting on all standable levels each call: fresh 12000-tick digging rose
            -- 93 -> 108, but the calibrated 3600-tick horizon FELL 84 -> 69 and the
            -- mature fort 111 -> 98. Designations spread over four levels send miners
            -- walking instead of digging.
            --
            -- Depth first, climbing only when a level is exhausted, with the frontier
            -- back at 30: fresh returned to baseline (81..88 against 84) and the 12000
            -- plateau came back to exactly 93 -- no gain at all -- while the mature fort
            -- stayed 30% down at 78. On a mountain fort the surface levels ARE standable
            -- and full of wall, so the budget goes to chambers far from the miners.
            --
            -- So the 93-tile plateau is not level availability, and this is not the way
            -- to break it. Spend ordinary wall cuts at the deepest landing: on a fresh
            -- embark the upper layers are soil and the staircase yields no usable
            -- boulders, so walking top-down consumed the whole batch before reaching rock.
            --
            -- Keep cutting until the budget is met. This used to cut ONE chamber per
            -- call and stop: asked for 12, 30, 100 or 400 tiles it placed 12, 11, 11
            -- and 10, because a chamber is len x wide and the loop ran once. So `tiles`
            -- was an upper bound and never a target, and every working tier plateaued
            -- at 93 dug tiles -- eight calls a run, about twelve each -- which two
            -- rounds of digging-more-levels work then failed to explain, because the
            -- map was never the limit. Rotate through the directions and let the
            -- frontier walk carry each one outward; four directions in a row placing
            -- nothing means the band within MAX_REACH is spent, and the verb says so.
            local turn, idle = 0, 0
            deferred = 0
            while placed < n and idle < #DIRS and turn < 64 do
                local before_turn = placed
                local d = DIRS[((P.digring + turn) % #DIRS) + 1]
                for dz = depth, 1, -1 do
                    chamber(oz - dz, d)
                    if placed >= n then break end
                end
                if placed == before_turn then idle = idle + 1 else idle = 0 end
                turn = turn + 1
            end
            -- Said even when NOTHING was placed: a zero with the reason "everything
            -- reachable is already marked" is the verb working, and a zero without it is
            -- indistinguishable from the verb being broken.
            if placed < n and (placed > 0 or deferred > 0) then
                if deferred > 0 then
                    note("designate_dig", string.format(
                        "designated %d of the %d asked; the rest lies behind rock that is "
                        .. "marked but not yet dug, so it cannot be reached -- ask again "
                        .. "once these are cut", placed, n))
                else
                    note("designate_dig", string.format(
                        "designated %d of the %d asked: the band within %d tiles of the "
                        .. "shaft holds no more undug wall on the levels the fort can reach",
                        placed, n, MAX_REACH))
                end
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
            -- How much this verb has ever designated in this fort. The observer emits it
            -- so a policy can see its own backlog -- designated minus dug -- and decide
            -- whether the miners have work, instead of asking on a fixed cadence or
            -- carrying a guessed weight. The evolved player found "bank the digging and
            -- go quiet" without being able to see when the bank ran out.
            _G.BONSAI_DESIGNATED = (_G.BONSAI_DESIGNATED or 0) + placed
            -- Reported LAST and as a note, because by here the chambers have been cut:
            -- a blocked shaft bounds how deep the fort goes, it does not stop it digging.
            if blocked_at then
                note("designate_dig", string.format(
                    "the shaft at %d,%d meets damp stone at z=%d, which DF will not mine "
                    .. "and whose designation it deletes; dug %d level(s) and designated "
                    .. "%d tile(s) in chambers off those landings instead",
                    ox, oy, blocked_at, depth, placed))
            end
        end)
    elseif verb == "build_room" then
        -- One idempotent, resumable request. All coordinates and requirements reaching
        -- this point were expanded by the trusted Python gate from the archived design.
        attempt("build_room", function()
            local r = room_from_args(a)
            advance_room(r)
            save_rooms()
            _G.BONSAI_LAST_ROOM = r
            c.build_room = c.build_room + 1
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
        --   a[9] fit test: 'dig' wants solid rock, anything else wants free floor
        --   a[10] the furniture the design places, as `b:1,c:1,t:1`
        --
        -- That last one is a trap dressed as a default. A .csv holds several blueprints
        -- and `quickfort run <file>` runs the FIRST. library/pump_stack.csv opens with a
        -- #notes help section, so running the file printed a walkthrough and stamped
        -- nothing; library/tombs/Mini_Saracen.csv worked only because its first section
        -- happens to be #dig. Anything else must be named as -n /<label>.
        attempt("apply_template", function()
            local name = a[2]
            local bw, bh = tonumber(a[3]), tonumber(a[4])
            local sx, sy = tonumber(a[6]) or 1, tonumber(a[7]) or 1
            if not (name and name ~= '' and bw and bh) then
                refuse("apply_template", "unknown template " .. tostring(name)
                       .. " or its footprint could not be read")
                return
            end

            -- Find somewhere it actually fits. reach.site checks every tile is a floor a
            -- citizen can stand on and nothing is already there, which is the difference
            -- between stamping a room and stamping it into a wall.
            -- its own placement cursor: sharing the stockpile one made every call
            -- retry the same 48 spots and compete with piles for them
            -- WHICH fit test depends on what the blueprint does, and getting this
            -- wrong made the verb refuse every dig design on a fort full of stone: a
            -- workshop needs a free floor, a crypt needs solid rock a miner can reach.
            -- Same wall-is-not-walkable distinction bonsai-reach was written around.
            -- WHERE THE FIRST STAGE WENT.
            --
            -- A design is stamped twice: the dig now, the zone and the furniture once the
            -- hole exists. The second call used to search for a site of its own and found
            -- a different one — the office was dug at 91,111 and furnished at 103,106,
            -- which is two half-rooms and no office. The verb remembers, keyed by the
            -- blueprint, so the later stages land on the earlier one.
            --
            -- THE MEMORY LIVES IN THE SAVE, not in a Lua global. A global survives between
            -- dfhack-run calls but dies with the process, and when this one died mid-test
            -- the fort came back with a dug room nobody could name — the next stage would
            -- have searched for a fresh site and split the design in two again. The owner
            -- asked for exactly this: the marker has to be in the GAME, not only in our
            -- own head. `saveSiteData` is written into the save file with the fort.
            P.tmpl = (P.tmpl or 0)
            local STAMP_KEY = 'bonsai/stamped'
            local function stamps()
                local ok, v = pcall(dfhack.persistent.getSiteData, STAMP_KEY)
                if ok and type(v) == 'table' then return v end
                return {}
            end
            local digs = (a[9] or 'dig') == 'dig'
            local x0, y0, z0
            local remembered = stamps()[name]
            if remembered and not digs then
                x0, y0, z0 = remembered[1], remembered[2], remembered[3]
            else
                x0, y0, z0 = find_site(bw, bh, 6, P.tmpl, 48, digs)
                if not x0 then
                    refuse("apply_template", "no site fits " .. tostring(name)
                           .. " (" .. tostring(bw) .. "x" .. tostring(bh) .. ")")
                    return
                end
                P.tmpl = P.tmpl + 1
                if digs then
                    local all = stamps()
                    all[name] = { x0, y0, z0 }
                    pcall(dfhack.persistent.saveSiteData, STAMP_KEY, all)
                end
            end

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
            -- RAISE THE ORDERS THE DESIGN IMPLIES.
            --
            -- DF will not let you place a bed that does not exist, so a design naming
            -- five pieces the fort has never made is a request nobody can act on. Order
            -- only the SHORTFALL: a fort that already has the chair does not need
            -- another, and an order placed every time the template is stamped would
            -- bury the manager.
            --
            -- The placement itself is deferred by DFHack's buildingplan, which quickfort
            -- calls when it applies the `#build` section — verified enabled on this
            -- instance, and it holds the plan IN THE GAME and swaps it for the real
            -- building when the item appears. That is the marker, so nothing here keeps
            -- a private list of what it is waiting for.
            local after_dig = digs
            local ordered = {}
            -- The design's furniture, resolved all the way down. This used to raise a work
            -- order per shortfall and stop there, which on a fort with no carpenter and no
            -- logs is an order nobody can ever work: three planned buildings sat at stage
            -- 0/1 with an empty manager list. `resolve_pieces` splices in the felling and
            -- the workshop first, so the request carries its own prerequisites.
            if not digs then
                resolve_pieces(a[10])
                for _, step in ipairs(RESOLVE_LOG) do ordered[#ordered + 1] = step end
            end
            if #ordered > 0 then
                c.add_workorder = c.add_workorder + dispatch_orders()
            end

            -- Ask the engine to rescan, exactly as designate_dig does. DF only looks
            -- at blocks flagged as carrying new designations, so without this a
            -- perfectly good stamp produces zero dig jobs and the caller has to know to
            -- poke it by hand — which is not a thing a verb should require.
            if after_dig then
                for x = x0, x0 + bw - 1 do
                    for y = y0, y0 + bh - 1 do
                        local blk = dfhack.maps.getTileBlock(x, y, z0)
                        if blk then blk.flags.designated = true end
                    end
                end
                pcall(function() df.global.process_dig = true end)
                pcall(function() df.global.process_jobs = true end)
            end

            local after = census()
            _G.BONSAI_LAST_TEMPLATE = { name = name, x = x0, y = y0, z = z0,
                                        w = bw, h = bh, new = after - before,
                                        ordered = table.concat(ordered, ', ') }
            if after > before then
                c.apply_template = c.apply_template + 1
            end
        end)
    elseif verb == "create_stockpile" then
        attempt("create_stockpile", function()
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
                if not placed then
                    refuse("create_stockpile", string.format(
                        "no free 2x2 site a citizen can reach was found in 48 tries "
                        .. "(%d of %d placed)", c.create_stockpile, n))
                    break
                end
            end
        end)
    elseif verb == "build_workshop" then
        -- Without a workshop no manager order can ever be worked, so `workorders_done`
        -- was structurally pinned at 0 and half the development weight was unearnable.
        attempt("build_workshop", function()
            local name = a[2] or "Carpenters"
            local deferred = a[3] == "deferred"
            local sub = df.workshop_type[name]
            -- Silent returns are how this verb reported 0 with no reason at all in the
            -- coverage audit. Say which precondition failed.
            -- Refuse an unknown kind rather than substituting. This used to read
            -- `if sub == nil then sub = df.workshop_type.Carpenters end`, the same
            -- silent-substitution shape that turned `add_workorder NoSuchJobType 5`
            -- into five beds: the agent asks for a Still, gets a carpenter, and the
            -- brewing it was planning quietly never happens.
            if sub == nil then
                print('REFUSED build_workshop: no such workshop kind ' .. tostring(name))
                return
            end
            -- ASK DF WHAT THIS WORKSHOP IS MADE OF. It used to hand every kind a log
            -- (or a boulder for the stone shops), which is right for the fifteen shops
            -- whose filter is "any building material" and a lie for the rest. Read live
            -- from `getFiltersByType`, DF's own table:
            --
            --     Quern              a manufactured QUERN item
            --     Millstone          a MILLSTONE item + TRAPPARTS
            --     Ashery             BLOCKS + an EMPTY barrel + a bucket
            --     Dyers              an EMPTY barrel + a bucket
            --     MetalsmithsForge   an ANVIL + a fire-safe building material
            --     MagmaForge         an ANVIL + a magma-safe building material
            --     Siege              three building materials, not one
            --
            -- Handing a Quern a log does not fail loudly. DFHack builds the job from
            -- whatever items you pass, so the job carries a reagent, our success guard
            -- (`#b.jobs[0].items > 0`) fires, and the fort gets a building it can never
            -- finish. Passing the FILTERS instead makes DF record the real requirement
            -- and pick the items itself, exactly as it does for a player.
            local filters = {}
            local got = pcall(function()
                filters = dfhack.buildings.getFiltersByType({}, df.building_type.Workshop,
                                                            sub, -1) or {}
            end)
            if not got then
                print('REFUSED build_workshop: DF gave no filters for ' .. tostring(name))
                return
            end
            local want = #filters
            -- A direct request still refuses an impossible workshop. A resolver-created
            -- request is different: its earlier queue entries have already designated
            -- the tree or rock that will supply this filter, so register it with
            -- buildingplan and let the game fulfil it when that material appears.
            for fi, f in ipairs(filters) do
                local okmat, have = can_supply(f, REACH_GROUPS)
                if not okmat and not deferred then
                    print(string.format(
                        'REFUSED build_workshop: %s needs filter %d of %d and the fort has '
                        .. '%d usable item(s) for it (wagon contents do not count: DF '
                        .. 'refuses them as building material)',
                        tostring(name), fi, want, have or 0))
                    return
                end
            end
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
                    local b
                    pcall(function()
                        b = dfhack.buildings.constructBuilding{
                            type = df.building_type.Workshop, subtype = sub,
                            pos = { x = x, y = y, z = z }, filters = filters }
                    end)
                    -- Count it only if DF attached a build job carrying EVERY requirement
                    -- the filter table declares. The count before this was "the job has at
                    -- least one item", which a Quern holding a log satisfies.
                    local reqs = 0
                    if b and #b.jobs > 0 then
                        pcall(function() reqs = #b.jobs[0].job_items.elements end)
                    end
                    local planned = false
                    if b and deferred then
                        pcall(function()
                            local bp = require('plugins.buildingplan')
                            if bp.isPlannableBuilding(df.building_type.Workshop, sub, -1) then
                                bp.addPlannedBuilding(b)
                                bp.scheduleCycle()
                                planned = bp.isPlannedBuilding(b)
                            end
                        end)
                    end
                    if b and (planned or reqs >= want) then
                        c.build_workshop = c.build_workshop + 1
                        return
                    elseif b then
                        -- do not leave a half-specified building standing: it would read
                        -- as a workshop to every observer that counts buildings
                        pcall(function() dfhack.buildings.deconstruct(b) end)
                    end
                end
            end
        end)
    elseif verb == "build_workshop_cluster" then
        -- A related group of workshops, the stockpiles that feed them, and the link
        -- between the two. The owner asked for the cluster to be chosen on declared
        -- numbers — cost, capability, what it replenishes — and those live in the python
        -- library; this receives the resolved membership and does what it is told:
        --   a[2] cluster name (for the record only)
        --   a[3] members, "W:Carpenters,W:Still" — W for workshop, F for furnace
        --   a[4] stockpile categories, "food,wood,furniture"
        --   a[5] width  a[6] height of the whole row
        attempt("build_workshop_cluster", function()
            local name = a[2]
            if not name or name == '' then
                refuse("build_workshop_cluster", "no cluster name given")
                return
            end
            -- A refusal nobody can read is a refusal nobody can act on, and this verb has
            -- five separate ways to decline.
            -- "A refusal nobody can read is a refusal nobody can act on" is what the
            -- comment above says, and then this stored the reason in a global and never
            -- printed it. Five ways to decline, all of them silent. Print it too.
            local function decline(why)
                _G.BONSAI_LAST_CLUSTER = nil
                _G.BONSAI_CLUSTER_REASON = why
                refuse("build_workshop_cluster", why)
            end
            _G.BONSAI_CLUSTER_REASON = nil
            local members = {}
            for token in tostring(a[3] or ''):gmatch('[^,]+') do
                local kind, what = token:match('^(%a):(.+)$')
                local btype, sub
                if kind == 'W' then
                    btype, sub = df.building_type.Workshop, df.workshop_type[what]
                elseif kind == 'F' then
                    btype, sub = df.building_type.Furnace, df.furnace_type[what]
                end
                -- refuse the whole cluster rather than build the part we understood
                if sub == nil then
                    return decline('no such building: ' .. tostring(token))
                end
                members[#members + 1] = { btype = btype, sub = sub, what = what }
            end
            if #members == 0 then
                refuse("build_workshop_cluster", "no such cluster: " .. tostring(name))
                return
            end

            -- ALL OR NOTHING. The declared observable is "every workshop in the cluster
            -- exists and is reachable", so half a cluster is a failure that looks like a
            -- success: the buildings would be counted, the capability would not be there,
            -- and the missing member is the one the rest were built for. Check every
            -- member can be supplied BEFORE placing any of them.
            for _, m in ipairs(members) do
                local filters = {}
                local got = pcall(function()
                    filters = dfhack.buildings.getFiltersByType({}, m.btype, m.sub, -1) or {}
                end)
                if not got then
                    return decline('could not read the filters for ' .. m.what)
                end
                for _, f in ipairs(filters) do
                    if not can_supply(f, REACH_GROUPS) then
                        return decline('the fort cannot supply ' .. m.what)
                    end
                end
                m.filters = filters
            end

            -- ONE contiguous block, workshops edge to edge with the stockpiles flush
            -- against them.
            --
            -- Each member used to get its own `find_site`, which scattered them: measured
            -- on the live fort, the last `survival` cluster had its two shops 10 tiles
            -- apart and its piles 9, 10 and 10 tiles from the shop they feed. That is not
            -- a cluster, it is three buildings that happen to be linked, and the link does
            -- nothing for distance — it only constrains which items are candidates.
            --
            -- DFHack's own shipped blueprints answer the layout and they agree with each
            -- other: embark.csv is a 15x3 row of four 3x3 shops sharing edges with a
            -- 15-wide stockpile slab abutting it at gap 0, and dreamfort's industry level
            -- has 25 of its 28 workshops with a stockpile tile at Chebyshev distance 0,
            -- median 0. Neither cuts corridors inside the block: the stockpile band IS
            -- the lane.
            local sizes, total_w, max_h = {}, 0, 0
            for _, m in ipairs(members) do
                local fw, fh = 3, 3
                pcall(function()
                    local a, b2 = dfhack.buildings.getCorrectSize(1, 1, m.btype, m.sub, -1)
                    if a then fw = a end
                    if b2 then fh = b2 end
                end)
                sizes[#sizes + 1] = { w = fw, h = fh }
                total_w = total_w + fw
                if fh > max_h then max_h = fh end
            end
            -- the pile band is two rows deep under the shop row, and wide enough for
            -- every 2x2 pile side by side
            local npiles = 0
            for _ in tostring(a[4] or ''):gmatch('[^,]+') do npiles = npiles + 1 end
            local blockw = math.max(total_w, npiles * 2)
            local blockh = max_h + 2
            local bx, by, bz = find_site(blockw, blockh, 6, P.cluster or 0, 24)
            P.cluster = (P.cluster or 0) + 1
            if not bx then
                return decline(string.format('no free %dx%d site for the whole block',
                    blockw, blockh))
            end

            local built = {}
            local cursor = 0
            for mi, m in ipairs(members) do
                local fw, fh = sizes[mi].w, sizes[mi].h
                -- constructBuilding takes the CENTRE of a workshop, not its corner
                local x = bx + cursor + math.floor(fw / 2)
                local y = by + math.floor(fh / 2)
                local z = bz
                cursor = cursor + fw
                local b
                pcall(function()
                    b = dfhack.buildings.constructBuilding{
                        type = m.btype, subtype = m.sub,
                        pos = { x = x, y = y, z = z }, filters = m.filters }
                end)
                local reqs = 0
                if b and #b.jobs > 0 then
                    pcall(function() reqs = #b.jobs[0].job_items.elements end)
                end
                if b and reqs >= #m.filters then
                    built[#built + 1] = b
                elseif b then
                    pcall(function() dfhack.buildings.deconstruct(b) end)
                    break
                else
                    _G.BONSAI_CLUSTER_REASON = 'constructBuilding refused ' .. m.what
                    break
                end
            end

            if #built < #members then
                -- undo, so a partial cluster is never left standing
                for _, b in ipairs(built) do
                    pcall(function() dfhack.buildings.deconstruct(b) end)
                end
                return decline(_G.BONSAI_CLUSTER_REASON
                    or string.format('only %d of %d members could be placed',
                                     #built, #members))
            end

            -- The stockpiles that feed it.
            local piles = {}
            local pile_x = 0
            for cat in tostring(a[4] or ''):gmatch('[^,]+') do
                local c2 = pile_category(cat)
                if c2 then
                    -- Flush against the shop row, stepping across the band. The bounds
                    -- check has to look at the slot we are ABOUT to use, not the next
                    -- one: incrementing first sent the last pile of every full band off
                    -- to the old scatter, 19 tiles from the shops it feeds.
                    local x, y, z
                    if pile_x + 2 <= blockw then
                        x, y, z = bx + pile_x, by + max_h, bz
                        pile_x = pile_x + 2
                    else
                        -- the band really is full; scatter rather than overlap
                        x, y, z = find_site(2, 2, 4, P.stock, 24)
                        P.stock = P.stock + 1
                    end
                    if x then
                        local pb
                        pcall(function()
                            pb = dfhack.buildings.constructBuilding{
                                type = df.building_type.Stockpile, abstract = true,
                                pos = { x = x, y = y, z = z }, width = 2, height = 2 }
                        end)
                        if pb then
                            pile_apply(pb, { c2 }, 'set')
                            piles[#piles + 1] = pb
                        end
                    end
                end
            end

            -- LINK BOTH SIDES. A stockpile carries `links` directly; a workshop does NOT
            -- — its four vectors live at `profile.links`, enumerated live because a
            -- one-sided link is this project's signature failure and has already cost it
            -- the noble seat and the room owner twice.
            for _, pb in ipairs(piles) do
                for _, b in ipairs(built) do
                    pcall(function()
                        pb.links.give_to_workshop:insert('#', b)
                        b.profile.links.take_from_pile:insert('#', pb)
                    end)
                end
            end

            -- and send workers to it, which is the half the owner asked for by name.
            local taken, staffed = {}, 0
            for _, b in ipairs(built) do
                local u = worker_for(b, taken)
                if u then
                    local okw = assign_worker(b, u)
                    if okw then
                        taken[u.id] = true
                        staffed = staffed + 1
                    end
                end
            end

            c.build_workshop_cluster = c.build_workshop_cluster + 1
            _G.BONSAI_LAST_CLUSTER = { name = name, shops = #built, piles = #piles,
                                       staffed = staffed }
        end)
    elseif verb == "assign_noble" then
        attempt("assign_noble", function()
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
            elseif not u then
                refuse("assign_noble", string.format(
                    "no citizen could be picked for %s out of %d", tostring(code), #cits))
            else
                -- assign_noble() has four ways to answer false and they mean different
                -- things to a caller. Silent on the fresh embark because the seat was
                -- empty; silent on the mature fort because it is already filled, which
                -- reads as a broken verb rather than as "nothing to do".
                local ent = df.global.plotinfo.main.fortress_entity
                local pos, holder = nil, nil
                if ent then
                    for _, pp in ipairs(ent.positions.own) do
                        if pp.code == code then pos = pp break end
                    end
                    if pos then
                        for _, asg in ipairs(ent.positions.assignments) do
                            if asg.position_id == pos.id and asg.histfig ~= -1 then
                                holder = df.historical_figure.find(asg.histfig)
                                break
                            end
                        end
                    end
                end
                if not pos then
                    refuse("assign_noble", string.format(
                        "this fortress has no %s position", tostring(code)))
                elseif holder then
                    refuse("assign_noble", string.format(
                        "%s is already held by %s", tostring(code),
                        tostring(dfhack.df2console(dfhack.units.getReadableName(holder)
                                 or "someone"))))
                else
                    refuse("assign_noble", string.format(
                        "DF refused the %s seat for the chosen dwarf", tostring(code)))
                end
            end
        end)
    elseif verb == "add_workorder" then
        -- BULK CREATION: make N of X, once. No condition, no schedule — those belong to
        -- add_workorder_conditional. They are one struct inside DF and two different
        -- things to want (tools/df_docs/open_decisions.md); merging them made the simple
        -- request step over five arguments it does not use.
        --
        --   add_workorder  ConstructBed  20  wood
        attempt("add_workorder", function()
            -- Refuse a job we have no workshop-and-reagent rule for. This used to read
            -- `... and a[2] or "ConstructBed"`, which silently turned a request for
            -- anything unknown into beds — measured: `add_workorder NoSuchJobType 5`
            -- queued five ConstructBed jobs.
            local jname = a[2]
            if not (jname and spec_for(jname)) then
                refuse("add_workorder", "no workshop-and-reagent rule for job "
                       .. tostring(jname))
                return
            end
            place_order {
                job = jname, amount = tonumber(a[3]) or 10,
                material = a[4] or "", freq = "OneTime", cond = nil,
            }
            -- The counter has always been what DISPATCHED, not what was placed, so an
            -- order that lands in the ledger and waits for a workshop reported zero and
            -- said nothing. That reads as a broken verb and is not one: measured on a
            -- fresh embark, ConstructBed sat correctly in the ledger while every
            -- workshop kept being deleted for want of a legal reagent.
            local sent = dispatch_orders()
            c.add_workorder = c.add_workorder + sent
            if sent == 0 then
                -- spec_for returns the VARIANTS of a job, each naming the workshop that
                -- can do it, so report all of them rather than guessing at the first.
                local shops, seen = {}, {}
                for _, variant in ipairs(spec_for(jname) or {}) do
                    if variant.shop and not seen[variant.shop] then
                        seen[variant.shop] = true
                        shops[#shops + 1] = variant.shop
                    end
                end
                local have = 0
                for _, b in ipairs(w.buildings.all) do
                    if df.building_workshopst:is_instance(b) and built(b)
                        and seen[tostring(df.workshop_type[b.type])] then
                        have = have + 1
                    end
                end
                refuse("add_workorder", string.format(
                    "%s is queued in the ledger but nothing can work it yet: it needs a "
                    .. "built %s and the fort has %d",
                    tostring(jname),
                    #shops > 0 and table.concat(shops, " or ") or "workshop",
                    have))
            end
        end)
    elseif verb == "add_workorder_conditional" then
        -- AUTOMATION: watch a stock level and refill it without being asked again.
        -- Read off a hand-played fort, that is `MakeAsh x_/10 Daily WHILE LessThan 10 of
        -- BAR (ASH)` — the amount is the FULL order, and the condition is what makes it
        -- go quiet once the shelf is full.
        --
        --   add_workorder_conditional  ConstructBarrel  BARREL  5  10  LessThan  ""  Daily
        attempt("add_workorder_conditional", function()
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
        attempt("create_zone", function()
            local kind = a[2]
            if not (kind and ZONE_KINDS[kind]) then
                refuse("create_zone", "no such zone kind: " .. tostring(kind))
                return
            end
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
            if not x then
                refuse("create_zone", "no reachable site for a " .. tostring(kind) .. " zone")
                return
            end
            if make_zone(kind, x, y, z, width, height) then
                c.create_zone = c.create_zone + 1
            end
        end)
    elseif verb == "ensure_furniture" then
        -- The requirement closure as a first-class action: "I need these pieces to exist"
        -- expands into felling, workshops and orders, spliced in ahead of the rest of this
        -- request. Separate from apply_template so it can be asked for on its own — and so
        -- it can be tested without stamping a blueprint to test it.
        attempt("ensure_furniture", function()
            local before = #RESOLVE_LOG
            resolve_pieces(a[2])
            if #RESOLVE_LOG > before then
                c.ensure_furniture = c.ensure_furniture + 1
            end
        end)
    elseif verb == "assign_room" then
        -- Give a room to somebody. An unowned bedroom is furniture in a hole.
        attempt("assign_room", function()
            local kind = a[2]
            local want = kind and ZONE_KINDS[kind] and df.civzone_type[ZONE_KINDS[kind]]
            if not want then
                local known = {}
                for k in pairs(ZONE_KINDS) do known[#known + 1] = k end
                table.sort(known)
                refuse("assign_room", "no such room kind: " .. tostring(kind)
                       .. "; try " .. table.concat(known, ", "))
                return
            end
            local unit = pick_citizen(a[3], true)
            if not unit then
                refuse("assign_room", "no dwarf matched " .. tostring(a[3]))
                return
            end
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
        attempt("place_furniture", function()
            local spec = FURNITURE[a[2] or ""]
            if not spec then
                refuse("place_furniture", "no placement rule for " .. tostring(a[2]))
                return
            end
            local count = math.max(1, math.min(tonumber(a[3]) or 1, 10))
            local made = 0
            for _ = 1, count do
                -- This verb installs furniture, it does not make it. On a fresh embark
                -- nothing has been built yet, so the honest answer is that there is no
                -- such item to place - which used to be a bare break, indistinguishable
                -- from a broken verb.
                local item = free_furniture(spec.item)
                if not item then
                    if made == 0 then
                        refuse("place_furniture", "no free " .. tostring(spec.item)
                               .. " to install; make one first (add_workorder Construct"
                               .. tostring(spec.building) .. ")")
                    end
                    break
                end
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
                if not placed then
                    if made == 0 then
                        refuse("place_furniture", "a free " .. tostring(spec.item)
                               .. " exists but no reachable free floor tile was found for it")
                    end
                    break
                end
                made = made + 1
            end
        end)
    elseif verb == "set_dwarf_labor" then
        -- One dwarf, one labour. set_labor is a fort-wide switch; a player specialises.
        attempt("set_dwarf_labor", function()
            local unit = pick_citizen(a[2], false)
            if not unit then
                refuse("set_dwarf_labor", "no dwarf matched " .. tostring(a[2]))
                return
            end
            local lid, why = labor_id(a[3])
            if not lid then
                refuse("set_dwarf_labor", why)
                return
            end
            local on = not (a[4] == "False" or a[4] == "false" or a[4] == "0")
            unit.status.labors[lid] = on
            c.set_dwarf_labor = c.set_dwarf_labor + 1
        end)
    elseif verb == "cancel_dwarf_job" then
        -- Free a dwarf who is doing something less important than what is needed now.
        attempt("cancel_dwarf_job", function()
            local unit = pick_citizen(a[2], false)
            if not (unit and unit.job.current_job) then
                refuse("cancel_dwarf_job", unit and "that dwarf has no job to cancel"
                       or ("no dwarf matched " .. tostring(a[2])))
                return
            end
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
        attempt("configure_stockpile", function()
            local which = tonumber(a[2]) or 0
            local cat = pile_category(a[3])
            -- The comment here used to say "refuse an unknown category" beside a bare
            -- return that refused nothing. A comment describing behaviour the code does
            -- not have is worse than no comment: it stops the next reader looking.
            if not cat then
                refuse("configure_stockpile", "no such stockpile category: " .. tostring(a[3]))
                return
            end
            -- address a specific pile, so a fort with several can narrow them
            -- differently: one for food, one for wood, the way a player lays them out
            local piles = {}
            for _, b in ipairs(w.buildings.all) do
                if b:getType() == df.building_type.Stockpile then piles[#piles + 1] = b end
            end
            local target = piles[which + 1] or piles[1]
            if not target then
                refuse("configure_stockpile", "the fort has no stockpile to configure; "
                       .. "create_stockpile first")
                return
            end
            -- Disable every category, then enable the one asked for. Explicit rather
            -- than leaning on DFHack's 'set' mode, whose clearing behaviour we have not
            -- measured — and an unmeasured assumption is what this verb was made of.
            if not pile_apply(target, { cat }, 'set') then
                refuse("configure_stockpile", "DF rejected category " .. tostring(a[3])
                       .. " on that pile")
                return
            end

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
        attempt("chop_trees", function()
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
            if marked == 0 then
                local trees = 0
                for _, plant in ipairs(w.plants.all) do
                    if plant.tree_info then trees = trees + 1 end
                end
                refuse("chop_trees", string.format(
                    "the map has %d trees but none stood on a tile a citizen can reach "
                    .. "from where they are", trees))
            end
            if marked > 0 then
                pcall(function() df.global.process_dig = true end)
                c.chop_trees = c.chop_trees + marked
            end
        end)
    elseif verb == "smooth" then
        -- Smoothing raises a room's value and is the step before engraving. It applies
        -- to dug stone, so it needs a fort that has dug some.
        attempt("smooth", function()
            local n = math.max(1, math.min(tonumber(a[2]) or 20, 200))
            if not u1 then
                refuse("smooth", "the fort has no citizen to anchor the region on")
                return
            end
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
        attempt("build_construction", function()
            local kindname = a[2] or "Floor"
            local sub = df.construction_type[kindname]
            if sub == nil then
                refuse("build_construction", "no such construction kind: " .. tostring(a[2]))
                return
            end
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
                if not placed then
                    if c.build_construction == 0 then
                        refuse("build_construction", string.format(
                            "found material but no reachable free tile to build a %s on "
                            .. "in 12 tries", tostring(a[2])))
                    end
                    break
                end
            end
        end)
    elseif verb == "set_standing_order" then
        -- Fort-wide policy. Fifty of these exist as df.global.standing_orders_*, and the
        -- guide singles out refuse collection: leave it on and dwarves haul rotting
        -- vermin indoors, turn it off and the surface stays a rubbish tip.
        attempt("set_standing_order", function()
            local name = a[2]
            if not name or name == "" then
                refuse("set_standing_order", "no order name given")
                return
            end
            local key = "standing_orders_" .. name
            -- Indexing a field DF does not have RAISES, it does not return nil, so this
            -- guard never guarded anything: the error fell into the enclosing pcall and
            -- the verb reported zero with no reason. Measured on DF 53.16 -
            -- standing_orders_automelt does not exist and reading it throws
            -- "Cannot read field global.standing_orders_automelt: not found", while
            -- standing_orders_gather_refuse reads back 1. There are fifty of these.
            local readable = pcall(function() return df.global[key] end)
            if not readable then
                local known = {}
                pcall(function()
                    for k, _ in pairs(df.global) do
                        if type(k) == "string" and k:sub(1, 16) == "standing_orders_" then
                            known[#known + 1] = k:sub(17)
                        end
                    end
                end)
                table.sort(known)
                refuse("set_standing_order", string.format(
                    "DF has no standing order named %s; it has %d, for example %s",
                    tostring(name), #known,
                    table.concat({ known[1], known[2], known[3] }, ", ")))
                return
            end
            local on = not (a[3] == "False" or a[3] == "false" or a[3] == "0")
            df.global[key] = on and 1 or 0
            c.set_standing_order = c.set_standing_order + 1
        end)
    elseif verb == "set_dig_priority" then
        -- Priority is NOT a field on the map block, which is why a first look concluded
        -- the mechanic did not exist on this build. It lives in a block_square_event of
        -- type designation_priority, indexed by pos % 16 and stored as priority * 1000 вЂ”
        -- read out of DFHack's own quickfort/dig.lua rather than guessed at.
        attempt("set_dig_priority", function()
            local want = math.max(1, math.min(tonumber(a[2]) or 4, 7))
            if not u1 then
                refuse("set_dig_priority", "the fort has no citizen to anchor the region on")
                return
            end
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
        attempt("build_farm_plot", function()
            local pw = math.max(1, math.min(tonumber(a[2]) or 3, 10))
            local ph = math.max(1, math.min(tonumber(a[3]) or pw, 10))
            local want_plant = a[4] or ""       -- name the crop, or let it choose
            local x, y, z, crop, why = farm_site(pw, ph, want_plant)
            if not x then
                print('REFUSED build_farm_plot: ' .. tostring(why))
                return
            end
            local b = dfhack.buildings.constructBuilding {
                type = df.building_type.FarmPlot,
                pos = xyz2pos(x, y, z), width = pw, height = ph,
            }
            if not b then
                refuse("build_farm_plot", string.format(
                    "DF refused to place a %dx%d plot at %d,%d,%d", pw, ph, x, y, z))
                return
            end
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
    elseif verb == "brew_drink" then
        -- Brewing in DF 53.16 is not a BrewDrink job type. It is the raws-defined
        -- BREW_DRINK_FROM_PLANT custom reaction. The live probe proved that a bare job
        -- is cancelled and that copying the reaction's own two reagents (processable
        -- unrotten plant + empty food-storage container) produces drink 0 -> 1.
        local ok, why = pcall(function()
            local want = math.max(1, math.min(tonumber(a[2]) or 1, 5))
            local still = nil
            for _, b in ipairs(w.buildings.all) do
                if df.building_workshopst:is_instance(b)
                    and b.type == df.workshop_type.Still and built(b) then
                    still = b
                    break
                end
            end
            -- level 0: an intentional refusal is a message for the agent, not a stack
            -- trace. Without it the reason arrives prefixed with the lua file and line,
            -- which tells the reader about our source and nothing about their fort.
            if not still then
                error('the fort has no built Still; build_workshop Still first', 0)
            end

            local reaction, reaction_id = nil, nil
            for i, r in ipairs(w.raws.reactions.reactions) do
                if tostring(r.code) == 'BREW_DRINK_FROM_PLANT' then
                    reaction, reaction_id = r, i
                    break
                end
            end
            if not reaction then
                error('the BREW_DRINK_FROM_PLANT reaction is absent from the raws', 0)
            end

            local existing = 0
            for _, job in ipairs(still.jobs) do
                if job.job_type == df.job_type.CustomReaction
                    and tostring(job.reaction_name) == 'BREW_DRINK_FROM_PLANT' then
                    existing = existing + 1
                end
            end

            local queued = 0
            for _ = existing + 1, want do
                local job = df.job:new()
                job.job_type = df.job_type.CustomReaction
                job.reaction_name = reaction.code
                job.pos = xyz2pos(still.centerx, still.centery, still.z)
                dfhack.job.addGeneralRef(job, df.general_ref_type.BUILDING_HOLDER, still.id)
                still.jobs:insert('#', job)
                dfhack.job.linkIntoWorld(job, true)

                local copied, copy_ok = 0, true
                for _, reagent in ipairs(reaction.reagents) do
                    local one_ok = pcall(function()
                        local ji = df.job_item:new()
                        ji.item_type = reagent.item_type
                        ji.item_subtype = reagent.item_subtype
                        ji.mat_type = reagent.mat_type
                        ji.mat_index = reagent.mat_index
                        ji.quantity = reagent.quantity
                        ji.vector_id = df.job_item_vector_id.IN_PLAY
                        ji.reaction_id = reaction_id
                        for _, flags in ipairs({ 'flags1', 'flags2', 'flags3' }) do
                            for key, value in pairs(reagent[flags]) do
                                if value == true then ji[flags][key] = true end
                            end
                        end
                        job.job_items.elements:insert('#', ji)
                        copied = copied + 1
                    end)
                    if not one_ok then copy_ok = false; break end
                end
                if not copy_ok or copied ~= #reaction.reagents then
                    pcall(function() dfhack.job.removeJob(job) end)
                    error(string.format('copied %d of %d reaction reagents',
                                        copied, #reaction.reagents))
                end
                queued = queued + 1
            end
            c.brew_drink = c.brew_drink + ((queued > 0 or existing >= want) and 1 or 0)
            print(string.format('BREW target=%d existing=%d queued=%d reagents=%d',
                                want, existing, queued, #reaction.reagents))
        end)
        if not ok then print('REFUSED brew_drink: ' .. tostring(why)) end
    elseif verb == "set_crop" then
        -- Which crop, in which season, PER PLOT: a surface plot and a dug-out one want
        -- different plants, and sowing the wrong one is invisible — the plot reads as
        -- planted and grows nothing.
        attempt("set_crop", function()
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
            -- Sowing nothing is the normal case before a plot exists, and it used to be
            -- indistinguishable from a broken verb: zero counter, no reason.
            if n > 0 then
                c.set_crop = c.set_crop + 1
            else
                local plots = 0
                for _, b in ipairs(w.buildings.all) do
                    if b:getType() == df.building_type.FarmPlot then plots = plots + 1 end
                end
                if plots == 0 then
                    refuse("set_crop", "the fort has no farm plot to sow")
                else
                    refuse("set_crop", string.format(
                        "%d plot(s) but no seed for %s that will grow there",
                        plots, tostring(want)))
                end
            end
        end)
    elseif verb == "set_kitchen_flag" then
        -- The two clicks that decide a second year: cooking seeds destroys next year's
        -- crop, and cooking drink turns the beer supply into meals.
        attempt("set_kitchen_flag", function()
            local item = a[2]                       -- SEEDS or DRINK
            local allowed = (a[3] == "true" or a[3] == "True" or a[3] == "1")
            local itype = df.item_type[item]
            if itype == nil then
                refuse("set_kitchen_flag", "no such item type: " .. tostring(a[2]))
                return
            end
            -- exc_types is vector<kitchen_exc_type> and holds TYPED values. Inserting
            -- the integer 0 raises "incompatible object type", and so does the enum
            -- member. Measured on the mature save, which has 210 exclusions:
            --   integer 0        -> incompatible object type
            --   kitchen_exc_type -> incompatible object type
            --   copy of exc_types[0] -> accepted
            -- dfhack.kitchen does expose addExclusion/findExclusion/removeExclusion, but
            -- every argument order tried against this build answered "Cannot write field
            -- (global).findExclusion()", so the module is not usable from lua here.
            -- Copy an element the vector already holds; fall back to the plain value on a
            -- fort that has no exclusions yet, which is the case the fresh embark proved
            -- works. This was invisible until the mature fort exercised it.
            local k = df.global.plotinfo.kitchen
            local function push_exc()
                if #k.exc_types > 0 then
                    k.exc_types:insert('#', k.exc_types[0])
                else
                    k.exc_types:insert('#', 0)
                end
            end
            local changed, reached = 0, 0
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
                            push_exc()
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
            else
                refuse("set_kitchen_flag", string.format(
                    "the fort holds no %s to allow or forbid", tostring(a[2])))
            end
        end)
    end
end

-- What the request had to unfold into to be satisfiable. Printed rather than counted: a
-- caller that asked for an office and got a felling crew deserves to see why.
if #RESOLVE_LOG > 0 then
    print('RESOLVED ' .. #RESOLVE_LOG .. ' prerequisite(s):')
    for _, step in ipairs(RESOLVE_LOG) do print('  - ' .. step) end
end

-- Every dispatch is a visit from the manager: re-check each order's schedule and its
-- condition, and queue whatever is armed. This is the visit DF's own manager would pay
-- and never does on our forts.
local dispatched = dispatch_orders()
if dispatched > 0 then c.add_workorder = c.add_workorder + dispatched end
save_ledger()
ensure_order_pump()

local rep = {}
for k, v in pairs(c) do rep[#rep + 1] = k .. "=" .. v end
table.sort(rep)
print("APPLY " .. table.concat(rep, " "))
