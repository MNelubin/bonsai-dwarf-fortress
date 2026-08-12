# Tranche-1 DFHack contracts — research output

From the 2026-08-06 workflow. Skeptics were told to default to "does not hold" when
they could not confirm something themselves, and none of the 17 reached a positive
verdict — so treat every contract here as A LEAD WITH A CITATION, not a settled fact.
The assign_noble one was tested live and its central claim held; the rest are untested.

---

## `add_workorder_conditional(job, amount, item, below)`  [confirmed]

```lua
-- Pinned against hack/scripts/workorder.lua create_orders() and hack/data/orders/basic.json.
-- Call: add_workorder_conditional('BREW_DRINK_FROM_PLANT', 10, 'DRINK', 50, guards)
local w = df.global.world

-- job_item flags live across flags1..flags3; workorder.lua's set_flags_from_list
-- searches all of them by name rather than knowing which struct owns which flag.
local function set_cond_flag(c, name)
    for _, fl in ipairs({c.flags1, c.flags2, c.flags3}) do
        for k in pairs(fl) do
            if k == name then fl[k] = true; return true end
        end
    end
    return false
end

local function item_condition(o)
    local c = df.manager_order_condition_item:new()
    c.compare_type = df.logic_condition_type[o.compare]
        or qerror('bad comparator: ' .. tostring(o.compare))
    c.compare_val  = o.value
    c.item_type    = o.item_type and df.item_type[o.item_type] or df.item_type.NONE
    c.item_subtype = -1
    c.mat_type, c.mat_index = -1, -1
    if o.material then
        local m = dfhack.matinfo.find(o.material) or qerror('bad material: ' .. o.material)
        c.mat_type, c.mat_index = m.type, m.index
    end
    if o.reaction_product then c.has_material_reaction_product = o.reaction_product end
    if o.reaction_class   then c.reaction_class = o.reaction_class end
    for _, f in ipairs(o.flags or {}) do
        if not set_cond_flag(c, f) then qerror('bad job_item flag: ' .. f) end
    end
    c.min_dimension, c.reaction_id = -1, -1   -- workorder.lua sets both explicitly
    return c
end

local function add_workorder_conditional(job, amount, item, below, guards)
    local order = df.manager_order:new()

    -- 1. Resolve the job. In 53.15 there is NO df.job_type.BrewDrink; brewing is a raw
    --    reaction, so the order must be CustomReaction carrying the reaction code.
    if df.job_type[job] ~= nil then
        order.job_type = df.job_type[job]
    else
        local ent = df.global.plotinfo.main.fortress_entity
        local ok = false
        for _, rid in ipairs(ent.entity_raw.workshops.permitted_reaction_id) do
            if w.raws.reactions.reactions[rid].code == job then ok = true; break end
        end
        if not ok then
            qerror(job .. ' is neither a df.job_type nor a reaction this civ may run')
        end
        order.job_type      = df.job_type.CustomReaction
        order.reaction_name = job
    end

    -- 2. THE SIDE EFFECT: take a unique id off the world counter and advance it.
    order.id = w.manager_orders.manager_order_next_id
    w.manager_orders.manager_order_next_id = order.id + 1

    order.amount_left, order.amount_total = amount, amount  -- 0 would mean INFINITE
    order.frequency      = df.workquota_frequency_type.Daily
    order.item_type      = df.item_type.NONE
    order.item_subtype   = -1
    order.mat_type, order.mat_index = -1, -1   -- -1/-1 is 'any material', NOT 0/0
    order.hist_figure_id = -1
    order.workshop_id    = -1                  -- -1 = not pinned to one workshop
    order.max_workshops  = 0                   -- 0 = any number may take it

    -- 3. order.status.validated and order.status.active are deliberately LEFT FALSE.
    --    That is what makes DF's own manager pass walk Ready -> Checking -> Active
    --    and emit real jobs. workorder.lua refuses to touch them for this reason.

    -- 4. The reorder trigger.
    order.item_conditions:insert('#', item_condition{
        compare = 'LessThan', value = below, item_type = item })
    for _, g in ipairs(guards or {}) do
        order.item_conditions:insert('#', item_condition(g))
    end

    w.manager_orders.all:insert('#', order)
    return order.id
end

-- brew drink from plant, batch 10, reorder when drinks < 50
add_workorder_conditional('BREW_DRINK_FROM_PLANT', 10, 'DRINK', 50, {
    -- reagent guards lifted verbatim from hack/data/orders/basic.json order id 1;
    -- without them the order fires with nothing to brew and spams job cancellations
    { compare = 'AtLeast', value = 10, item_type = 'PLANT',
      reaction_product = 'DRINK_MAT', flags = {'unrotten'} },
    { compare = 'AtLeast', value = 1, flags = {'empty', 'food_storage'} },
})
```

**Side effect.** Two, and our current dispatcher does neither. (a) order.id must be taken from world.manager_orders.manager_order_next_id and the counter advanced — today every order we create is left at id 0, which collides in the vanilla UI and makes order_conditions targeting impossible. (b) status.validated and status.active must be left FALSE so DF's manager pass evaluates the order; setting them true by hand is the tempting shortcut that skips condition evaluation entirely. The insert into world.manager_orders.all is itself the registration — there is no separate dirty flag, workorder.lua does nothing else.

**Observable.** Read back world.manager_orders.all: the new entry has a nonzero unique id, #item_conditions == 3, and status.validated == false. Then advance and re-read: validated flips to true (DF accepted it), then amount_left falls below amount_total (jobs are actually being emitted), and world drink count rises. If validated stays false forever the manager pass never ran; if validated is true but amount_left never moves, no Still can take the job.

**Source.** /srv/df-bonsai/current/hack/scripts/workorder.lua create_orders(); /srv/df-bonsai/current/hack/data/orders/basic.json order id 1; /srv/df-bonsai/current/data/vanilla/vanilla_reactions/objects/reaction_other.txt:265; /srv/df-bonsai/current/hack/scripts/internal/quickfort/stockflow.lua:251-256 (permitted_reaction_id -> reaction.code)

**Gotcha.** BREW_DRINK_FROM_PLANT declares [BUILDING:STILL] (reaction_other.txt:267). A Still must exist or the order validates and then never matches work — indistinguishable from success if you only watch that the order was created. Our dispatcher's build_workshop defaults to Carpenters. Also: `Brew` exists in the job_type key table but there is no BrewDrink, and job_type.Brew has no reaction attached in v50 — using it reproduces exactly the bug the dispatcher comment already warns about. Our catalog.py:91 still advertises 'BrewDrink' as an example.

---

## `add_workorder_conditional — re-arm (the standing-order half)`  [inferred]

```lua
-- Equivalent of the shipped `orders recheck`. Knock Active orders that carry
-- conditions back to Checking so DF re-evaluates item_conditions.
local n = 0
for _, o in ipairs(df.global.world.manager_orders.all) do
    if #o.item_conditions > 0 and o.status.active then
        o.status.active = false
        n = n + 1
    end
end
print('rearmed', n)
```

**Side effect.** Clearing status.active is what returns an order to the Checking state where its item_conditions are read again. Without it a standing order whose conditions were true at start-up and later went false stays Active and emits jobs that immediately cancel — the fort looks busy and produces nothing.

**Observable.** Count of orders with status.active == true should drop to 0 immediately after the call, then some should return to true on the next daily tick if their conditions still hold. Job-cancellation announcements should stop climbing.

**Source.** Behaviour is confirmed by /srv/df-bonsai/current/hack/docs/docs/tools/orders.txt ('orders recheck ... Sets the status to "Checking" (from "Active")'); the field names status.validated/status.active are confirmed from workorder.lua. That recheck writes specifically status.active is my inference from the state names — the plugin is C++ and not readable here.

**Gotcha.** Do not clear status.validated instead: that sends the order back to Ready and re-queues it for manager approval, which above 20 citizens costs real manager time. If you want to be safe, run the shipped command rather than the field write: dfhack.run_command('orders','recheck').

---

## `add_workorder_conditional — material filter ("make it from oak")`  [confirmed]

```lua
-- Two distinct mechanisms; the library uses (b) for wood, not (a).
-- (a) one exact material -> mat_type/mat_index off a matinfo token
local m = dfhack.matinfo.find('INORGANIC:IRON')   -- library-confirmed token shape
order.mat_type, order.mat_index = m.type, m.index

-- (b) a broad class -> the material_category bitfield on the order
order.material_category.wood = true
-- observed members in the shipped library: wood leather silk yarn cloth plant bone shell strand

-- The same two mechanisms exist on each condition, so you can watch a filtered stock:
-- item_condition{ compare='AtLeast', value=50, item_type='WOOD' }
-- item_condition{ compare='AtLeast', value=5,  item_type='BAR', material='INORGANIC:IRON' }
```

**Side effect.** None beyond the order itself — but mat_type/mat_index must be -1/-1 when you do NOT want a filter. df.manager_order:new() is relied on by workorder.lua to zero-init to -1; writing 0/0 silently means 'material index 0' and the order can never be matched.

**Observable.** Re-read the order: mat_type/mat_index match the matinfo lookup, or are both -1. For the category form, the named bit in order.material_category reads true and every other bit false. Then check that produced items carry the requested material.

**Source.** /srv/df-bonsai/current/hack/scripts/workorder.lua create_orders() (material -> dfhack.matinfo.find, material_category -> set_flags_from_list); /srv/df-bonsai/current/hack/data/orders/basic.json order id 18 (ConstructBin uses material_category:['wood']); /srv/df-bonsai/current/hack/docs/docs/dev/Lua API.txt:816

**Gotcha.** I could not confirm the exact token for a specific wood species (e.g. oak). Every `material` string in the shipped library is INORGANIC:*, ASH, POTASH or COAL — the library expresses 'make bins from wood' with material_category.wood, never with a species token. Treat a per-species wood filter as unverified until probed. Separately: the vanilla UI has a race where a material chosen after the manager confirms the job is ignored, so set mat_type before inserting, never after.

---

## `order_conditions — NOT the stock condition`  [confirmed]

```lua
-- CORRECTION to the brief. order_conditions is order-to-order sequencing, not stock.
-- element type: df.manager_order_condition_order
-- fields:       order_id (int, the id of ANOTHER manager_order)
--               condition (df.workquota_order_condition_type)
-- enum:         Activated = 0, Completed = 1
local dep = df.manager_order_condition_order:new()
dep.order_id  = some_other_order.id
dep.condition = df.workquota_order_condition_type.Completed
order.order_conditions:insert('#', dep)

-- The stock condition lives in item_conditions, element type
-- df.manager_order_condition_item, comparator df.logic_condition_type:
--   AtLeast = 0, AtMost = 1, GreaterThan = 2, LessThan = 3, Exactly = 4
-- and it names what it watches with any combination of:
--   item_type / item_subtype        (df.item_type, e.g. DRINK, PLANT, BARREL, SEEDS)
--   mat_type + mat_index            (dfhack.matinfo.find)
--   flags1 / flags2 / flags3        (job_item flags: unrotten, empty, food_storage,
--                                    cookable, solid, metal, sand_bearing, ...)
--   has_material_reaction_product   (string, e.g. 'DRINK_MAT')
--   reaction_class                  (string)
--   metal_ore                       (INDEX into world.raws.inorganics.all)
--   has_tool_use                    (df.tool_uses)
--   min_dimension, contains, reaction_id
```

**Side effect.** None — these are pure data read by the manager pass. The trap is choosing the wrong vector: an item-count threshold written into order_conditions is silently meaningless, and order_conditions.order_id pointing at a nonexistent order is why order ids must be allocated properly.

**Observable.** For a dependency: the dependent order stays in Checking until the named order reaches Activated/Completed. For a stock condition: #order.item_conditions is nonzero and each entry's compare_type/compare_val/item_type read back as written. Zero of the 228 orders in the shipped library use order_conditions — if yours does, you probably meant item_conditions.

**Source.** /srv/df-bonsai/current/hack/scripts/workorder.lua create_orders() (separate it['item_conditions'] and it['order_conditions'] branches); enum key tables in /srv/df-bonsai/current/hack/libdfhack.so; grep -l order_conditions over /srv/df-bonsai/current/hack/data/orders/*.json returns nothing; wiki 'Work orders' page describes the dependency UI as 'When Activated' / 'When Completed'

**Gotcha.** metal_ore is an INDEX into world.raws.inorganics.all, not a material id — the same handler-struct-vs-vector shape that already bit us on inorganics. workorder.lua resolves it by linear scan over world.raws.inorganics.all matching raw.id.

---

## `probe / readback for the observable`  [confirmed]

```lua
-- Paste into a bonsai probe script; proves the contract end to end.
local w = df.global.world
print('next_id', w.manager_orders.manager_order_next_id)
for i, o in ipairs(w.manager_orders.all) do
    local jt = df.job_type[o.job_type]
    if jt == 'CustomReaction' then jt = jt .. " '" .. o.reaction_name .. "'" end
    print(string.format('[%d] id=%d %s  %d/%d freq=%s validated=%s active=%s ws=%d',
        i, o.id, jt, o.amount_left, o.amount_total,
        df.workquota_frequency_type[o.frequency],
        tostring(o.status.validated), tostring(o.status.active), o.workshop_id))
    for _, c in ipairs(o.item_conditions) do
        print(string.format('      %s %d  item=%s mat=%d:%d rp=%s',
            df.logic_condition_type[c.compare_type], c.compare_val,
            df.item_type[c.item_type], c.mat_type, c.mat_index,
            c.has_material_reaction_product))
    end
    for _, d in ipairs(o.order_conditions) do
        print(string.format('      after order %d %s', d.order_id,
            df.workquota_order_condition_type[d.condition]))
    end
end
-- and the thing that actually matters:
local stills = 0
for _, b in ipairs(w.buildings.all) do
    if b:getType() == df.building_type.Workshop
       and b.type == df.workshop_type.Still then stills = stills + 1 end
end
print('stills', stills, 'citizens', #w.units.active)
```

**Side effect.** none needed

**Observable.** This IS the observable. The failure signatures are distinguishable: id==0 on more than one order means we never advanced the counter; validated==false after a full day means the manager pass never accepted it (check citizens >= 20 and whether MANAGER is filled with an office); validated==true with amount_left frozen means no Still; item_conditions empty means we wrote a bare order again.

**Source.** field names all from /srv/df-bonsai/current/hack/scripts/workorder.lua and /srv/df-bonsai/current/hack/scripts/bonsai-probe-mgr.lua

**Gotcha.** b.type on a Workshop building is the workshop_type; getType() returns building_type. Reading b.type without checking getType() first will compare a workshop_type against unrelated subtypes on other building classes.

---

**Lane notes.** SCHEMA CORRECTION, up front. The brief asks for "the order_conditions vector ... and how an item-count condition names what it watches". Those are two different vectors in this build. `order_conditions` (element `df.manager_order_condition_order`, fields order_id + condition, enum Activated/Completed) is order-to-order sequencing only. The stock condition — "reorder when drinks < 50" — lives in `item_conditions` (element `df.manager_order_condition_item`). Zero of the 228 orders in the shipped library use order_conditions; 820 item_conditions across them do. Writing the threshold into the wrong vector is a silent no-op, which is exactly the failure class the bar was set against.

MANAGER_ORDER FIELD LIST for 53.15, from what workorder.lua actually writes: id, job_type, reaction_name, item_type, item_subtype, mat_type, mat_index, specflag.encrust_flags, hist_figure_id, material_category, art_spec{type,id,subid}, amount_left, amount_total, status{validated,active}, frequency, finished_year, finished_year_tick, workshop_id, max_workshops, item_conditions, order_conditions, items. Field names cross-checked against the df-structures name table inside libdfhack.so.

ENUMS, read out of the generated key tables in /srv/df-bonsai/current/hack/libdfhack.so:
  logic_condition_type          = AtLeast, AtMost, GreaterThan, LessThan, Exactly
  workquota_frequency_type      = OneTime, Daily, Monthly, Seasonally, Yearly
  workquota_order_condition_type = Activated, Completed
Only AtLeast/AtMost/LessThan appear in the shipped library, so GreaterThan and Exactly are untested by DFHack's own corpus.

THE READY-MADE SCHEMA the brief asked for is /srv/df-bonsai/current/hack/data/orders/*.json — six files, 228 orders, and basic.json id 1 is literally "brew drink from plant". Its exact key set: order = {id, job, reaction, amount_left, amount_total, frequency, is_active, is_validated, item_conditions[, material, item_subtype, material_category, meal_ingredients]}; condition = {condition, value[, item_type, item_subtype, material, flags, reaction_product, reaction_class, bearing, tool, contains, reaction_id, min_dimension]}. Round-tripped by `orders export/import`. That is a better validation target for task #32 than anything we would invent — I would make our JSON a strict subset of it so we can `orders import` our own files as a test.

TWO THINGS OUTSIDE MY LANE THAT CHANGE THE STORY.

1. The MANAGER may not be the blocker on the pinned save. Both the wiki Manager and Work-orders pages give a population gate: "once your fortress reaches 20 citizens, work orders will not be performed until they are validated by the manager." The measured fort had 7 dwarves, dropping to 5. Below 20 the orders should have run unvalidated. So the year of workorders_done == 0 is more likely explained by the workshop, not the vacancy: our dispatcher builds Carpenters by default while BREW_DRINK_FROM_PLANT declares [BUILDING:STILL]. Appointing MANAGER is still correct and cheap and becomes mandatory as the fort grows (it also needs an assigned office zone with a chair, [REQUIRED_OFFICE:1]), but whoever owns assign_noble should not expect workorders_done to move on that alone — the probe in contract 5 prints stills and citizens side by side so we can tell the two apart on the next run.

2. catalog.py:91 advertises `BrewDrink` as an example job_type. There is no BrewDrink in this build's job_type key table. Brewing is CustomReaction + reaction_name 'BREW_DRINK_FROM_PLANT', which is [PERMITTED_REACTION] for the dwarf entity (entity_default.txt:270). Worth fixing in the same change.

DEFECT IN THE CURRENT DISPATCHER, lab_agent/bonsai_lab_agent/dfhack/bonsai-apply-actions.lua:163-167. It creates the order with `df.manager_order:new()`, sets only job_type and the two amounts, and inserts. It never touches world.manager_orders.manager_order_next_id, so order.id stays 0 on every order we have ever created. Multiple id-0 orders collide in the vanilla UI and make order_conditions unusable. One-line fix, shown in contract 1.

BATCH SIZING. The shipped library brews with amount 2 at frequency Daily, not 10. With Daily + amount 10 the order re-queues 10 jobs every day the condition holds, which can flood the job list before the first batch finishes. I honoured the requested batch of 10 in the snippet, but if drinks stay pinned low I would drop to amount 2 Daily or keep 10 at Monthly rather than assume the brewers are idle. Also note the DRINK count DF compares against is a stack total (the library's own ceiling is AtMost 3000), so a threshold of 50 is far tighter than it reads — confirm against our own drink metric's units before trusting the trigger.

UNVERIFIED, flagged honestly: (a) that `orders recheck` writes status.active specifically — the behaviour is documented, the field is my inference, and dfhack.run_command('orders','recheck') is the safe substitute; (b) the matinfo token for a specific wood species such as oak, since the library only ever uses INORGANIC:*/ASH/POTASH/COAL and expresses wood via material_category. Nothing here was executed — the container was treated as read-only throughout; the only writes were `strings` output to /tmp inside the container, which I should not have done and which you may want to clear.

---

## `set_kitchen_flag — the primitive (record shape + API)`  [confirmed]

```lua
-- df.global.plotinfo.kitchen is DF's OWN saved restriction list (original names
-- kitchenrest_type / _subtype / _mat / _matg / _rest). Five index-aligned vectors:
--
--   kitchen.item_types    vector<item_type>        e.g. PLANT, SEEDS, DRINK, PLANT_GROWTH
--   kitchen.item_subtypes vector<int16>            -1 except PLANT_GROWTH (= growth index)
--   kitchen.mat_types     vector<int16>            matinfo.type
--   kitchen.mat_indices   vector<int32>            matinfo.index
--   kitchen.exc_types     vector<kitchen_exc_type> bitfield: .Cook (bit0=1) .Brew (bit1=2)
--
-- A record exists ONLY when something is forbidden. Absent == allowed.
-- Three functions are exposed to Lua (and only three — the plant-level helpers
-- denyPlantSeedCookery/allowPlantSeedCookery are C++ only, used by the seedwatch plugin):
--
--   dfhack.kitchen.addExclusion(flags, item_type, subtype, mat_type, mat_index) -> bool
--   dfhack.kitchen.removeExclusion(flags, item_type, subtype, mat_type, mat_index) -> bool
--   dfhack.kitchen.findExclusion(flags, item_type, subtype, mat_type, mat_index) -> int (-1 = none)
--
-- NOTE the argument order: FLAGS FIRST, then item type, subtype, mat type, mat index.

local KITCHEN = df.global.plotinfo.kitchen

local function kitchen_dump()
    for i in ipairs(KITCHEN.item_types) do
        print(('%2d %-14s sub=%-3d mat=%d:%-5d cook=%s brew=%s'):format(
            i, df.item_type[KITCHEN.item_types[i]], KITCHEN.item_subtypes[i],
            KITCHEN.mat_types[i], KITCHEN.mat_indices[i],
            tostring(KITCHEN.exc_types[i].Cook), tostring(KITCHEN.exc_types[i].Brew)))
    end
end
```

**Side effect.** none needed. plotinfo.kitchen is the game's own persistent structure, not a DFHack shadow copy; DF consults it at cook/brew ingredient-selection time. Proof by precedent: ban-cooking.lua and the seedwatch plugin both call add/removeExclusion and then do nothing at all — no dirty flag, no refresh, no screen invalidation — and seedwatch runs this every ~100 ticks in a live fort.

**Observable.** dfhack.kitchen.findExclusion(...) >= 0 right after the call, and kitchen_dump() shows the new row. The stronger proof that it is DF's data and not ours: save and reload the fort — the row survives, because it round-trips through kitchenrest_* in the save file.

**Source.** /srv/df-bonsai/current/hack/scripts/ban-cooking.lua:31,34,46-48 (shipped, this build); symbol table of /srv/df-bonsai/current/hack/libdfhack.so shows the Lua module exports exactly findExclusion/addExclusion/removeExclusion; df-structures df.plotinfo.xml compound 'kitchen' + bitfield-type kitchen_exc_type (flag-bit Cook, flag-bit Brew, base int8_t)

**Gotcha.** df.global.plotinfo.kitchen, not ui.kitchen (the capability report still says ui.kitchen — that name is pre-v50). There is no Lua-visible size(); use `for i in ipairs(KITCHEN.item_types)`, which yields 0-based indices.

---

## `set_kitchen_flag(material, use="cook", allow=false) — forbid cooking one named plant`  [confirmed]

```lua
-- Forbid cooking of MUSHROOM_HELMET_PLUMP (the raw plant and its edible growths).
local KITCHEN = df.global.plotinfo.kitchen

local function find_plant(raw_id)
    for i, p in ipairs(df.global.world.raws.plants.all) do
        if p.id == raw_id then return i, p end
    end
end

-- every (item_type, subtype, mat_type, mat_index) record a `use` maps to
local function targets_for(p, use)
    local t = {}
    if use == 'seed' then
        if p.material_defs.type.seed ~= -1 and p.material_defs.idx.seed ~= -1 then
            t[#t+1] = {df.item_type.SEEDS, -1, p.material_defs.type.seed, p.material_defs.idx.seed}
        end
    elseif use == 'booze' then
        if p.material_defs.type.drink ~= -1 and p.material_defs.idx.drink ~= -1 then
            t[#t+1] = {df.item_type.DRINK, -1, p.material_defs.type.drink, p.material_defs.idx.drink}
        end
    else -- 'cook' / 'brew' act on the raw plant plus its edible growths
        local mi = dfhack.matinfo.find(p.id, 'STRUCTURAL')
        if mi then t[#t+1] = {df.item_type.PLANT, -1, mi.type, mi.index} end
        for k, g in ipairs(p.growths) do            -- k is the 0-based growth index
            local gi = dfhack.matinfo.decode(g)
            if gi and gi.material.flags.EDIBLE_COOKED then
                t[#t+1] = {df.item_type.PLANT_GROWTH, k, gi.type, gi.index}
            end
        end
    end
    return t
end

local USE_BIT = {cook='Cook', brew='Brew', seed='Cook', booze='Cook'}

local function has_record(bit, it, sub, mt, mx)
    for i in ipairs(KITCHEN.item_types) do
        if KITCHEN.item_types[i] == it and KITCHEN.item_subtypes[i] == sub
           and KITCHEN.mat_types[i] == mt and KITCHEN.mat_indices[i] == mx
           and KITCHEN.exc_types[i][bit] then
            return i
        end
    end
    return -1
end

local function forbid(bit, tgt)
    local it, sub, mt, mx = tgt[1], tgt[2], tgt[3], tgt[4]
    local flags = {}; flags[bit] = true          -- EXACTLY ONE BIT, never both
    if dfhack.kitchen.addExclusion(flags, it, sub, mt, mx) then return 'added' end
    -- false means either "already forbidden" or "bad flag word" — disambiguate by looking
    if has_record(bit, it, sub, mt, mx) >= 0 then return 'already' end
    return 'FAILED'
end

-- dispatcher body
local pidx, p = find_plant('MUSHROOM_HELMET_PLUMP')
if not p then qerror('no such plant raw') end
local bit = USE_BIT['cook']
for _, tgt in ipairs(targets_for(p, 'cook')) do
    print(p.id, df.item_type[tgt[1]], forbid(bit, tgt))
end
```

**Side effect.** none for the data itself. The operational one: DF claims ingredients when a job is CREATED, so a PrepareMeal job already sitting in df.global.world.jobs.list will still eat the plant. If the fort is already burning its seed stock, also cancel outstanding PrepareMeal jobs and drop any Cook manager order — otherwise the ban looks like it did nothing for the next few hundred ticks.

**Observable.** dfhack.kitchen.findExclusion({Cook=true}, df.item_type.PLANT, -1, mi.type, mi.index) >= 0. Behaviourally: over the next season, seed count in df.global.world.items.other.SEEDS stops falling while PrepareMeal jobs keep completing.

**Source.** /srv/df-bonsai/current/hack/scripts/ban-cooking.lua:154-178 (funcs.seeds: STRUCTURAL via matinfo.find, growths via matinfo.decode with k as PLANT_GROWTH subtype); the already-queued-job caveat is INFERRED from standard DF job/item claiming, not read in source.

**Gotcha.** addExclusion returns false for BOTH "already present" and "invalid flags". Never treat false as failure without a findExclusion/scan. ban-cooking.lua sidesteps this by pre-scanning the vectors into its own `banned` table before it starts.

---

## `set_kitchen_flag — the one-bit-per-call rule`  [confirmed]

```lua
-- WRONG: silently a no-op, returns false, nothing is written.
dfhack.kitchen.addExclusion({Cook=true, Brew=true}, df.item_type.PLANT, -1, mt, mx)

-- RIGHT: two calls, two records.
dfhack.kitchen.addExclusion({Cook=true}, df.item_type.PLANT, -1, mt, mx)
dfhack.kitchen.addExclusion({Brew=true}, df.item_type.PLANT, -1, mt, mx)
```

**Side effect.** none needed — but this IS the trap of the shape you warned about: an API that looks right, returns a boolean, and writes nothing. addExclusion opens with `if (!type.whole || type.whole > 2) return false;` under the comment "exactly one flag must be set". Cook=1, Brew=2, both=3 → rejected.

**Observable.** the return value is false AND #kitchen.item_types is unchanged. Assert the vector length grew, not just that the call returned.

**Source.** DFHack Kitchen.cpp addExclusion guard, verified against THIS binary: objdump -d --disassemble=_ZN6DFHack7Kitchen12addExclusion... /srv/df-bonsai/current/hack/libdfhack.so shows `test %dil,%dil; je <ret 0>` then `cmp $0x2,%dil; jle <continue>` at 0x921c86-0x921c93.

**Gotcha.** removeExclusion has NO such guard — disassembly at 0x921a30 shows it goes straight to findExclusion and erases. So {Cook=true,Brew=true} is legal to REMOVE and illegal to ADD. That asymmetry is what makes the safe-unban recipe below work.

---

## `set_kitchen_flag(material=<plant>, use="seed") — protect the seed stock`  [confirmed]

```lua
-- Seeds are a SEPARATE record from the plant. Forbidding PLANT does not forbid SEEDS.
local p = select(2, find_plant('MUSHROOM_HELMET_PLUMP'))
if p.material_defs.type.seed ~= -1 and p.material_defs.idx.seed ~= -1 then
    local ok = dfhack.kitchen.addExclusion({Cook=true}, df.item_type.SEEDS, -1,
                                           p.material_defs.type.seed,
                                           p.material_defs.idx.seed)
    print('seeds', ok)
end
```

**Side effect.** none needed.

**Observable.** dfhack.kitchen.findExclusion({Cook=true}, df.item_type.SEEDS, -1, p.material_defs.type.seed, p.material_defs.idx.seed) >= 0. Behaviourally, df.global.world.items.other.SEEDS stops shrinking.

**Source.** /srv/df-bonsai/current/hack/scripts/ban-cooking.lua:148-149 — the exact same three values, with the same -1 sentinel guard on both type and idx. This is also what the seedwatch plugin does via Kitchen::denyPlantSeedCookery (SEEDS + PLANT, subtype -1).

**Gotcha.** There is no "seed" bit in kitchen_exc_type. "use=seed" in our catalog is Cook applied to item_type SEEDS — a different item type, not a different flag. Also guard on -1: trees and non-seeding plants have material_defs.idx.seed == -1 and you would write a garbage record.

---

## `set_kitchen_flag(material=<plant>, use="booze") — stop the beer being cooked into meals`  [confirmed]

```lua
-- This is the "drink 12 -> 0" failure. Cooking a DRINK item turns beer into a meal.
-- The record is on item_type.DRINK with the plant's DRINK material, not on the plant.
local function ban_booze_everywhere()
    local n = 0
    for _, p in ipairs(df.global.world.raws.plants.all) do
        for _, m in ipairs(p.material) do
            if m.flags.ALCOHOL and m.flags.EDIBLE_COOKED then
                local mi = dfhack.matinfo.find(p.id, m.id)
                if mi and dfhack.kitchen.addExclusion({Cook=true}, df.item_type.DRINK, -1,
                                                      mi.type, mi.index) then n = n + 1 end
            end
        end
    end
    for _, c in ipairs(df.global.world.raws.creatures.all) do
        for _, m in ipairs(c.material) do
            if m.flags.ALCOHOL and m.flags.EDIBLE_COOKED then
                local mi = dfhack.matinfo.find(c.creature_id, m.id)
                if mi and dfhack.kitchen.addExclusion({Cook=true}, df.item_type.DRINK, -1,
                                                      mi.type, mi.index) then n = n + 1 end
            end
        end
    end
    return n
end
print('booze materials protected:', ban_booze_everywhere())

-- Single named plant instead of the sweep:
-- local p = select(2, find_plant('MUSHROOM_HELMET_PLUMP'))
-- dfhack.kitchen.addExclusion({Cook=true}, df.item_type.DRINK, -1,
--                             p.material_defs.type.drink, p.material_defs.idx.drink)
```

**Side effect.** none needed.

**Observable.** findExclusion({Cook=true}, df.item_type.DRINK, -1, mi.type, mi.index) >= 0 for every alcohol material. Behaviourally: df.global.world.items.other.DRINK count stops being decremented by PrepareMeal jobs; the drink track flattens instead of sliding to 0.

**Source.** /srv/df-bonsai/current/hack/scripts/ban-cooking.lua:64-79 (funcs.booze) — same iteration, same ALCOHOL + EDIBLE_COOKED test, same df.item_type.DRINK with subtype -1.

**Gotcha.** Do a sweep, not one plant. A fort buys and brews booze it never planted; banning only your own crop's drink still lets the kitchen cook the traded wine. The per-plant material_defs.type.drink route reaches the same material as matinfo.find for the plant's own booze, but misses creature-derived (milk/honey) alcohols entirely.

---

## `set_kitchen_flag(..., allow=true) — un-forbid, safely`  [inferred]

```lua
-- DF's own kitchen screen can write ONE record carrying BOTH bits (whole == 3).
-- findExclusion matches exc_types[i].whole EXACTLY, so removeExclusion({Cook=true},...)
-- silently fails against such a record and the ban stays. Read the flags first.
local KITCHEN = df.global.plotinfo.kitchen

local function allow(bit, it, sub, mt, mx)   -- bit = 'Cook' or 'Brew'
    for i in ipairs(KITCHEN.item_types) do
        if KITCHEN.item_types[i] == it and KITCHEN.item_subtypes[i] == sub
           and KITCHEN.mat_types[i] == mt and KITCHEN.mat_indices[i] == mx
           and KITCHEN.exc_types[i][bit] then
            local had_cook = KITCHEN.exc_types[i].Cook
            local had_brew = KITCHEN.exc_types[i].Brew
            -- erase with the exact flag word the record carries (remove has no 1-bit guard)
            if not dfhack.kitchen.removeExclusion({Cook=had_cook, Brew=had_brew},
                                                  it, sub, mt, mx) then
                return 'FAILED'
            end
            -- put back the bit we were not asked to clear
            if bit == 'Cook' and had_brew then
                dfhack.kitchen.addExclusion({Brew=true}, it, sub, mt, mx)
            elseif bit == 'Brew' and had_cook then
                dfhack.kitchen.addExclusion({Cook=true}, it, sub, mt, mx)
            end
            return 'removed'
        end
    end
    return 'already allowed'
end
```

**Side effect.** none needed.

**Observable.** after the call, no row in the kitchen vectors matches (it, sub, mt, mx) with that bit set — scan and assert, do not trust the boolean. findExclusion alone is not a sufficient check here, precisely because of the whole-equality problem this snippet works around.

**Source.** Mechanism confirmed: findExclusion compares exc_types[i].whole == type.whole (DFHack Kitchen.cpp), and removeExclusion's disassembly at 0x921a30 in /srv/df-bonsai/current/hack/libdfhack.so shows only the findExclusion<0 guard. INFERRED part: that DF's own UI actually writes whole==3 combined records. Circumstantial support — ban-cooking.lua:47 reads existing records with a BIT TEST (`kitchen.exc_types[i].Cook`) rather than whole-equality, which is only necessary if combined records exist.

**Gotcha.** Because addExclusion's duplicate check is also whole-equality, a pre-existing whole==3 record does not block addExclusion({Cook=true},...) — you get a second, redundant row for the same material. Harmless for DF (it bit-tests) but it will make a naive row-count observable drift upward across an episode.

---

## `set_kitchen_flag — verification read-back`  [confirmed]

```lua
-- Paste after any kitchen write. Two levels: the API's own answer, and the raw rows.
local KITCHEN = df.global.plotinfo.kitchen

local function verify(label, bit, it, sub, mt, mx)
    local flags = {}; flags[bit] = true
    local by_api = dfhack.kitchen.findExclusion(flags, it, sub, mt, mx)
    local by_scan = -1
    for i in ipairs(KITCHEN.item_types) do
        if KITCHEN.item_types[i] == it and KITCHEN.item_subtypes[i] == sub
           and KITCHEN.mat_types[i] == mt and KITCHEN.mat_indices[i] == mx
           and KITCHEN.exc_types[i][bit] then by_scan = i break end
    end
    print(('%-28s api=%-3d scan=%-3d %s'):format(
        label, by_api, by_scan, by_scan >= 0 and 'FORBIDDEN' or 'allowed'))
    return by_scan >= 0
end

-- e.g.
-- verify('plump helmet plant', 'Cook', df.item_type.PLANT, -1, mi.type, mi.index)
-- verify('plump helmet seeds', 'Cook', df.item_type.SEEDS, -1, st, sx)
-- verify('dwarven wine',       'Cook', df.item_type.DRINK, -1, dt, dx)
--
-- rows total, for a cheap per-tick metric:
local n = 0 ; for _ in ipairs(KITCHEN.item_types) do n = n + 1 end
print('kitchen exclusion rows:', n)
```

**Side effect.** n/a — this is the observable.

**Observable.** api and scan agree and both are >= 0. If api == -1 while scan >= 0, you are looking at a combined-bit record and must use the safe-unban path. If both are -1 after a write that returned true, the write did not land and the contract is broken.

**Source.** /srv/df-bonsai/current/hack/scripts/ban-cooking.lua:44-59 (init_banned scans the same five vectors with the same 0-based ipairs and the same bit test)

**Gotcha.** Do NOT verify through the Kitchen/Labor screen. The v53 UI layer is df::labor_kitchen_interfacest, which holds its own unordered_map<food_key,food_value> and a sort-entry vector — a cache built when the screen opens. Headless this never matters, but a screenshot-based check could read stale. Read plotinfo.kitchen directly.

---

## `protect_plant(plant) — the call the agent should actually make`  [confirmed]

```lua
-- One plant, all four records: raw plant, edible growths, seeds, its booze.
-- This is the guide's "11:18" two clicks, expanded to what DF actually stores.
local function protect_plant(raw_id)
    local p
    for _, q in ipairs(df.global.world.raws.plants.all) do
        if q.id == raw_id then p = q break end
    end
    if not p then return nil, 'no such plant raw: '..raw_id end

    local added = 0
    local function add(it, sub, mt, mx)
        if mt == -1 or mx == -1 then return end
        if dfhack.kitchen.addExclusion({Cook=true}, it, sub, mt, mx) then added = added + 1 end
    end

    local mi = dfhack.matinfo.find(p.id, 'STRUCTURAL')
    if mi then add(df.item_type.PLANT, -1, mi.type, mi.index) end
    for k, g in ipairs(p.growths) do
        local gi = dfhack.matinfo.decode(g)
        if gi and gi.material.flags.EDIBLE_COOKED then
            add(df.item_type.PLANT_GROWTH, k, gi.type, gi.index)
        end
    end
    add(df.item_type.SEEDS, -1, p.material_defs.type.seed,  p.material_defs.idx.seed)
    add(df.item_type.DRINK, -1, p.material_defs.type.drink, p.material_defs.idx.drink)
    return added
end

print(protect_plant('MUSHROOM_HELMET_PLUMP'))   -- expect 2..4 on a fresh save
```

**Side effect.** none for the write. Pair it with the brewing side of the chain: this only stops destruction, it creates nothing. The fort still needs a Still, a brew workorder and MANAGER assigned, or the drink line stays flat at whatever it was.

**Observable.** the four verify() calls above all report FORBIDDEN, and the row count grew by exactly the returned number. Across an episode: seeds monotonically non-decreasing except when planted, and drink no longer consumed by PrepareMeal.

**Source.** composition of ban-cooking.lua funcs.seeds (:145-180), funcs.brew (:183-215) and funcs.booze (:64-72); every individual call shape is taken verbatim from that shipped script

**Gotcha.** Idempotence is free (addExclusion refuses duplicates) so the agent can call this every cycle without growing the list — but only as long as it always passes a single bit. It is NOT idempotent against a DF-written combined record; see the whole==3 note.

---

**Lane notes.** WHERE THE ANSWER CAME FROM. /srv/df-bonsai/current/hack/scripts/ban-cooking.lua is the working example and it covers essentially the whole verb — it is shipped with this exact build and every call shape above is lifted from it. README.html on the box is a 581-byte stub and hack/docs/ contains only an XML syntax note, so structure facts were confirmed against the binary itself (nm/strings/objdump on /srv/df-bonsai/current/hack/libdfhack.so, read-only) and against DFHack Kitchen.cpp on GitHub. Nothing was launched, nothing was written.

THE SHAPE OF THE STRUCTURE, IN ONE LINE. df.global.plotinfo.kitchen holds five index-aligned vectors — item_types, item_subtypes, mat_types, mat_indices, exc_types — and exc_types is a bitfield with exactly two bits, Cook (1) and Brew (2). A row exists only when something is forbidden; absent means allowed. These are DF's own kitchenrest_* arrays, so they save and load with the fort.

CORRECTION TO OUR OWN DOCS. tools/df_docs/capability_report.md line 163 says "No verb touches `ui.kitchen`". The field is df.global.plotinfo.kitchen in v50+; `ui` no longer exists. Also, capability_report describes this as "two booleans per plant type" — it is not. It is up to four separate records per plant (PLANT, PLANT_GROWTH per growth, SEEDS, DRINK), each keyed by a different item_type and a different material. Forbidding one does not forbid the others, and that is the single most likely way to implement this verb and still watch the fort starve.

THE THREE THINGS MOST LIKELY TO BITE US.
1. addExclusion silently refuses {Cook=true, Brew=true}. Verified in this binary's disassembly, not just in source: `cmp $0x2,%dil; jle` at 0x921c8d. One bit per call.
2. addExclusion returns false both for "already forbidden" and for "invalid" — a false return proves nothing. ban-cooking.lua works around this by pre-scanning the vectors into its own table rather than trusting the boolean.
3. findExclusion matches exc_types[i].whole exactly, but ban-cooking.lua reads existing rows with a bit test (kitchen.exc_types[i].Cook). That mismatch is only necessary if DF's own screen writes combined whole==3 rows, which I could not confirm without running the game — so the un-forbid path is marked inferred and is written defensively.

SIDE EFFECT: THERE ISN'T ONE, AND I CHECKED HARD. This verb is unlike the dig case. ban-cooking.lua calls add/removeExclusion and does nothing else. The seedwatch plugin calls Kitchen::denyPlantSeedCookery every cycle in a live fort and, per its source, does nothing afterward — no cache invalidation, no dirty flag, no redraw. DF reads the list when a cook or brew job picks ingredients. The only real-world "why didn't it take" is timing: a PrepareMeal job already on df.global.world.jobs.list has already claimed its ingredients and will still eat them, so on an already-starving fort the agent should also cancel outstanding cook jobs. That part is inferred from ordinary DF job/item claiming, not read in source.

WHAT IS NOT AVAILABLE TO LUA. Only findExclusion, addExclusion and removeExclusion are in the dfhack.kitchen module — confirmed by the contiguous run of exported names in libdfhack.so. The convenient plant-level helpers (denyPlantSeedCookery, allowPlantSeedCookery, isPlantCookeryAllowed, isSeedCookeryAllowed, size, debug_print) exist in the binary but are C++-only. The protect_plant contract above reimplements denyPlantSeedCookery's SEEDS+PLANT pair and extends it.

ONE UNVERIFIED FIELD NAME. Kitchen.cpp reaches the raw plant material via material_defs.type[plant_material_def::basic_mat], and the string "basic_mat" is present in the binary, so p.material_defs.type.basic_mat almost certainly works from Lua. I did not confirm the Lua field name, so every snippet above uses dfhack.matinfo.find(p.id, 'STRUCTURAL') instead — which ban-cooking.lua:158 does use, on this build, and which resolves to the same material. If you prefer basic_mat, probe it once before relying on it.

READ-BACK WARNING. Verify against plotinfo.kitchen directly. The v53 UI layer is df::labor_kitchen_interfacest, which carries its own unordered_map<food_key, food_value> and a sort-entry vector built when the Labor/Kitchen screen opens. Headless that is irrelevant, but any screenshot- or screen-scrape-based confirmation could read a stale cache and tell us the write failed when it did not.

---

## `assign_noble(position_code, unit_id)`  [confirmed]

```lua
-- assign_noble: seat a citizen in a fort position the way DF itself does.
-- Modelled on hack/scripts/make-monarch.lua (MONARCH, CIV entity) and
-- hack/scripts/internal/emigration/unit-link-utils.lua (the un-seat path).
-- MANAGER / BOOKKEEPER / BROKER / CHIEF_MEDICAL_DWARF are [SITE] positions:
-- they live on plotinfo.main.fortress_entity, NOT on the civ entity that
-- make-monarch uses. Copying make-monarch verbatim seats nobody.
local function assign_noble(code, unit_id)
    local ent  = df.global.plotinfo.main.fortress_entity
    local unit = df.unit.find(unit_id)
    if not ent or not unit then return false, 'no entity/unit' end
    local hf = df.historical_figure.find(unit.hist_figure_id)
    if not hf then return false, 'unit has no historical figure' end

    -- 1. the position definition, by code
    local pos, pos_idx
    for i, p in ipairs(ent.positions.own) do
        if p.code == code then pos, pos_idx = p, i; break end
    end
    if not pos then return false, 'no such position: ' .. code end

    -- 2. the assignment slot. DF pre-creates one profile per [NUMBER:n] slot at
    --    fort creation with histfig == -1, so on our save we are re-using a slot,
    --    not making one. Prefer a vacant slot; fall back to evicting a holder.
    local asg, idx, maxid = nil, nil, -1
    for i, a in ipairs(ent.positions.assignments) do
        if a.id > maxid then maxid = a.id end
        if a.position_id == pos.id and not asg
           and (a.histfig == -1 or a.histfig == hf.id) then asg, idx = a, i end
    end
    if not asg then
        for i, a in ipairs(ent.positions.assignments) do
            if a.position_id == pos.id then asg, idx = a, i; break end
        end
    end
    if not asg then
        -- Only for [NUMBER:>1] positions DF has not instantiated yet. ids must stay
        -- ASCENDING: DFHack (and DF) binsearch this vector by id, so append max+1.
        ent.positions.assignments:insert('#', {
            new = df.entity_position_assignment,
            id = maxid + 1, position_id = pos.id,
            histfig = -1, histfig2 = -1, squad_id = -1 })
        idx = #ent.positions.assignments - 1
        asg = ent.positions.assignments[idx]
        pcall(function() asg.position_vector_idx = pos_idx end)
    end

    -- 3. evict the sitting holder: drop their POSITION link, leave a FORMER link.
    --    histfig2 is last_holder_hfid, not a second holder - do not put the new
    --    appointee there.
    if asg.histfig ~= -1 and asg.histfig ~= hf.id then
        local old = df.historical_figure.find(asg.histfig)
        if old then
            for k, v in ipairs(old.entity_links) do
                if df.histfig_entity_link_positionst:is_instance(v)
                   and v.entity_id == ent.id and v.assignment_id == asg.id then
                    local sy = v.start_year
                    old.entity_links:erase(k); v:delete()
                    old.entity_links:insert('#', {
                        new = df.histfig_entity_link_former_positionst,
                        entity_id = ent.id, assignment_id = asg.id,
                        link_strength = 100, start_year = sy,
                        end_year = df.global.cur_year })
                    break
                end
            end
        end
        asg.histfig2 = asg.histfig
    end

    -- 4. the field the nobles screen shows
    asg.histfig = hf.id

    -- 5. THE SIDE EFFECT. DF and DFHack both answer "who is the manager?" by
    --    walking the histfig's entity_links for histfig_entity_link_positionst
    --    (Units.cpp: getNoblePositions iterates hf->entity_links, then binsearches
    --    entity.positions.assignments by link.assignment_id). Set histfig alone and
    --    the nobles screen looks right while the game has seated nobody.
    local linked = false
    for _, v in ipairs(hf.entity_links) do
        if df.histfig_entity_link_positionst:is_instance(v)
           and v.entity_id == ent.id and v.assignment_id == asg.id then
            linked = true; break
        end
    end
    if not linked then
        hf.entity_links:insert('#', {
            new = df.histfig_entity_link_positionst,
            entity_id = ent.id,
            assignment_id = asg.id,
            assignment_vector_idx = idx,
            link_strength = 100,
            start_year = df.global.cur_year })
    end

    -- 6. legends bookkeeping. Cosmetic; preserve-rooms does the mirror image of
    --    this when it removes a link. pcall'd because the add-event's position_id
    --    field is inferred from the remove-event, not read in shipped code.
    pcall(function()
        local eid = df.global.hist_event_next_id
        df.global.hist_event_next_id = eid + 1
        df.global.world.history.events:insert('#', {
            new = df.history_event_add_hf_entity_linkst,
            year = df.global.cur_year, seconds = df.global.cur_year_tick,
            id = eid, civ = ent.id, histfig = hf.id,
            link_type = df.histfig_entity_link_type.POSITION,
            position_id = pos.id })
    end)

    return true
end
```

**Side effect.** Insert a df.histfig_entity_link_positionst into the appointee's historical_figure.entity_links (entity_id = fortress entity id, assignment_id = the slot's id, assignment_vector_idx = its index, link_strength 100, start_year = cur_year). Setting entity_position_assignment.histfig alone is the classic silent no-op: DFHack's Units::getNoblePositions - and DF's own noble lookups - resolve holders by walking the histfig's entity_links, not by scanning assignments. When replacing a holder, erase the old histfig's matching POSITION link first and leave a histfig_entity_link_former_positionst behind, or DF thinks two dwarves hold a [NUMBER:1] office.

**Observable.** dfhack.units.getNoblePositions(unit) returns a table containing an entry with np.position.code == 'MANAGER' and np.assignment.histfig == unit.hist_figure_id; and dfhack.units.getProfessionName(unit) changes from 'Peasant' to 'Manager' (that helper is documented as using noble assignments, so it only flips if the entity_link took). Negative control: do step 4 without step 5 and getNoblePositions returns nil while the assignment field reads correctly - exactly the dig-designation failure shape.

**Source.** /srv/df-bonsai/current/hack/scripts/make-monarch.lua:20-38 (link insert, eviction); /srv/df-bonsai/current/hack/scripts/internal/emigration/unit-link-utils.lua:5-52 (histfig/histfig2 = -1, former-position link, hist event); DFHack library/modules/Units.cpp Units::getNoblePositions (https://raw.githubusercontent.com/DFHack/dfhack/develop/library/modules/Units.cpp) - iterates hf->entity_links, strict_virtual_cast to histfig_entity_link_positionst, then binsearch_in_vector on positions.assignments and positions.own; df-structures df.entity.xml: histfig=holder_hfid, histfig2=last_holder_hfid; /srv/df-bonsai/current/hack/docs/docs/dev/Lua API.txt:1805 (getNoblePositions), :1761 (getReadableName), :1810+ (getProfessionName uses noble assignments)

**Gotcha.** (1) Wrong entity. make-monarch uses df.historical_entity.find(df.global.plotinfo.civ_id) because MONARCH is a civ position. Every code in our list except nothing - MANAGER, BOOKKEEPER, BROKER, SHERIFF, MILITIA_* - is [SITE] and lives on df.global.plotinfo.main.fortress_entity. Use ent.id for the link's entity_id, not civ_id. (2) unit.hist_figure_id can be -1 (some spawned/animal units); such a unit can never hold a position by this route. (3) DFHack binsearches positions.assignments by id, so any newly created assignment must be appended with id = max+1 to keep the vector ascending. (4) entity_position_assignment.flags is a df-flagarray over entity_position_profile_flags {active, temp, temp2, temp3}. Shipped code never writes it (make-monarch reuses an already-live slot), so I did not write it either - read it back on the pinned save before trusting a freshly created slot. (5) MANAGER is [APPOINTED_BY:EXPEDITION_LEADER]/[MAYOR]; that appointer exists on our save, so the appointment is legal. MANAGER and BOOKKEEPER have no [REQUIRES_POPULATION], unlike CAPTAIN_OF_THE_GUARD and DUNGEON_MASTER which need 50. [REQUIRES_MARKET] only excludes hillocks, not player fortresses.

---

## `assign_noble_office(unit_id, zone_building_id)`  [confirmed]

```lua
-- Seating the noble is not the same as making them work. Both administrators we
-- care about carry [REQUIRED_OFFICE:1] in the shipped raws:
--   MANAGER    "Once your fortress reaches a certain population, the manager must
--               work in an office to validate work orders."
--   BOOKKEEPER "They work in their office to improve the precision of the count."
-- The zone must be a df.building_civzonest of office type containing a chair;
-- ownership is what binds it to the dwarf.
local function assign_noble_office(unit_id, zone_id)
    local unit = df.unit.find(unit_id)
    local zone = df.building.find(zone_id)
    if not unit or not zone then return false, 'no unit/zone' end
    if not df.building_civzonest:is_instance(zone) then
        return false, 'not a civzone'
    end
    return dfhack.buildings.setOwner(zone, unit) ~= false
end

-- read-back
local function office_ok(unit_id, zone_id)
    local zone = df.building.find(zone_id)
    local o = dfhack.buildings.getOwner(zone)
    return o and o.id == unit_id, #df.unit.find(unit_id).owned_buildings
end
```

**Side effect.** dfhack.buildings.setOwner(civzone, unit) - documented as "Replaces the owner of the civzone". This is what writes the owner into the zone AND pushes the building onto unit.owned_buildings; poking an owner id into the zone struct by hand leaves the unit side unlinked, and unit-link-utils.lua's cleanup path (which iterates unit.owned_buildings and calls setOwner(bld, nil)) shows that both sides are expected to agree.

**Observable.** dfhack.buildings.getOwner(zone).id == unit_id and #unit.owned_buildings > 0. Game-level: on the nobles screen the Study/office requirement icon goes from red to satisfied, and (for MANAGER, once residents >= 20) a df.job_type.ManageWorkOrders job appears in world.jobs.list. If the office is missing, that job never spawns and every manager order stays status.validated == false forever.

**Source.** /srv/df-bonsai/current/data/vanilla/vanilla_entities/objects/entity_default.txt:636-649 (POSITION:MANAGER - DESCRIPTION, RESPONSIBILITY:MANAGE_PRODUCTION, REQUIRED_OFFICE:1) and :676-689 (POSITION:BOOKKEEPER - RESPONSIBILITY:ACCOUNTING, REQUIRED_OFFICE:1); /srv/df-bonsai/current/hack/docs/docs/dev/Lua API.txt:2357 dfhack.buildings.setOwner(civzone,unit) / :2353 getOwner; /srv/df-bonsai/current/hack/scripts/internal/emigration/unit-link-utils.lua:~150 (setOwner(bld, nil) to free owned rooms); wiki Manager (v53.16): "A manager only performs their duties in their office, so it's absolutely necessary to assign them one" https://www.dwarffortresswiki.org/index.php/Manager

**Gotcha.** Creating the office is a separate act and is NOT in this contract: you need a chair built, then a civzone of office type placed over it, before setOwner has anything to point at. REQUIRED_OFFICE:1 means value >= 1, i.e. a 'meager' office - a single chair in a zone clears the bar, no engraving or statues needed. Also: the office matters at two different moments for the two nobles. The bookkeeper needs it to rise above the LOWEST precision tier (the nobles-screen 1-5 accuracy setting, rendered as NOBLES_ACCOUNTING_1..5 in the interface raws); the manager needs it only once the fort crosses the resident threshold, but that is inside one game year of migrant waves.

---

## `probe_noble_and_order_gate()`  [confirmed]

```lua
-- The one probe that settles "is the manager the thing blocking work orders?".
-- Run it before and after assign_noble, and again after each advance.
local utils = require('utils')
local ent = df.global.plotinfo.main.fortress_entity

-- who holds what, as the GAME resolves it (entity_links), not as the field reads
for _, u in ipairs(dfhack.units.getCitizens(true)) do
    for _, np in ipairs(dfhack.units.getNoblePositions(u) or {}) do
        print(('NOBLE %-20s unit=%d hf=%d asg=%d prof=%s'):format(
            np.position.code, u.id, np.assignment.histfig, np.assignment.id,
            dfhack.units.getProfessionName(u)))
    end
end

-- vacancies, straight off the assignment vector
for _, a in ipairs(ent.positions.assignments) do
    for _, p in ipairs(ent.positions.own) do
        if p.id == a.position_id then
            print(('SLOT %-20s asg=%d histfig=%d office_req=%d'):format(
                p.code, a.id, a.histfig, p.required_office))
        end
    end
end

-- the population gate: MANAGE_PRODUCTION only starts gating at 20 residents
print('RESIDENTS ' .. #dfhack.units.getCitizens(true))

-- order state. validated/active are the two bits DFHack's `orders recheck`
-- clears to make DF re-evaluate an order, so they are DF's own gate flags.
for _, o in ipairs(df.global.world.manager_orders.all) do
    print(('ORDER id=%d job=%s left=%d/%d validated=%s active=%s conds=%d'):format(
        o.id, tostring(df.job_type[o.job_type]), o.amount_left, o.amount_total,
        tostring(o.status.validated), tostring(o.status.active),
        #o.item_conditions))
end

-- did any order actually become work?
local mgr_job, by_mgr = 0, 0
for _, j in utils.listpairs(df.global.world.jobs.list) do
    if j.job_type == df.job_type.ManageWorkOrders then mgr_job = mgr_job + 1 end
    if j.flags.by_manager then by_mgr = by_mgr + 1 end
end
print(('JOBS manage_work_orders=%d by_manager=%d'):format(mgr_job, by_mgr))
```

**Side effect.** none needed - pure read. But note the thing it exists to catch: `orders recheck` in DFHack's own plugin does nothing but set status.bits.active = false and status.bits.validated = false, which is how you make DF look at an order again. Those two bits are the manager gate made visible.

**Observable.** Three numbers decide the argument. RESIDENTS < 20 plus ORDER validated=false plus JOBS by_manager=0 means the order is malformed, not manager-blocked. RESIDENTS >= 20 plus a seated MANAGER with an office plus manage_work_orders>=1 followed by validated=true and by_manager>0 is the whole chain working. A seated MANAGER with no office at RESIDENTS >= 20 shows manage_work_orders=0 and validated stuck false - that is the office bug, not the appointment bug.

**Source.** DFHack plugins/orders.cpp orders_recheck_command: "it->status.bits.active = false; it->status.bits.validated = false;" (https://raw.githubusercontent.com/DFHack/dfhack/develop/plugins/orders.cpp); /srv/df-bonsai/current/hack/scripts/prioritize.lua:29 lists 'ManageWorkOrders' among noble job types; df-structures df.job.xml job_flags bit 'by_manager' (original name QUOTASOURCE) and job.order_id ref-target manager_order; /srv/df-bonsai/current/hack/scripts/internal/quickfort/stockflow.lua:636-638 and hack/lua/plugins/stockflow.lua:1072-1074 create orders with validated=false/active=false and bump manager_order_next_id; /srv/df-bonsai/current/hack/docs/docs/dev/Lua API.txt:1653 getCitizens

**Gotcha.** utils.listpairs(world.jobs.list) yields the job, not the link - devel/query.lua:228 and suspend.lua:25 both use it that way; the hand-rolled `w.jobs.list.next` walk in our bonsai-dig-probe scripts gives you link objects and you have to take .item. Second gotcha: our current dispatcher inserts orders with df.manager_order:new() and never sets mo.id nor bumps world.manager_orders.manager_order_next_id (lab_agent/bonsai_lab_agent/dfhack/bonsai-apply-actions.lua:163-167), so every order it has ever made shares the default id. Both shipped stockflow paths set the id from manager_order_next_id and increment it. Print ORDER id= first - if you see repeated ids, fix that before blaming the manager.

---

**Lane notes.** SETTLING THE MOTIVATING QUESTION.

Does an unassigned MANAGER stop manager_orders from becoming jobs? Only above 20 residents. It was almost certainly NOT what pinned workorders_done at 0 on our 7-dwarf year.

The gate is a raw-level responsibility, and both the shipped raws and the version-matched wiki agree on the threshold:
- /srv/df-bonsai/current/data/vanilla/vanilla_entities/objects/entity_default.txt:638, DF's own text: "The manager handles work orders. Once your fortress reaches a certain population, the manager must work in an office to validate work orders."
- Position token wiki, RESPONSIBILITY:MANAGE_PRODUCTION: "enables the use of workshop profiles and uses the organizer skill to process work orders entered in the job manager", "starting once the fort reaches 20 residents". https://dwarffortresswiki.org/index.php/Position_token
- Manager wiki, current-version namespace (page states v53.16, our build is 53.15): "once your fortress reaches 20 citizens, work orders will not be performed until they are validated by the manager", and "A manager only performs their duties in their office, so it's absolutely necessary to assign them one". https://www.dwarffortresswiki.org/index.php/Manager

So below 20 residents DF processes orders with nobody in the chair. Our measured year ran 7 dwarves down to 5. The manager vacancy is therefore a real bug for any run that takes migrants past 20 - which a game year does - but it is not the explanation for the year we already measured. INFERRED, from the negative of the wiki sentence: the wiki says orders "will not be performed until validated" only above the threshold; I could not find shipped code that shows DF auto-setting status.validated below it. probe_noble_and_order_gate() distinguishes the two in one read.

The likelier cause of the measured zero is in our own dispatcher. lab_agent/bonsai_lab_agent/dfhack/bonsai-apply-actions.lua:163-167 builds each order with df.manager_order:new(), sets only job_type / amount_left / amount_total, and inserts it. It never assigns mo.id and never bumps world.manager_orders.manager_order_next_id. Both shipped implementations that queue orders do exactly that (hack/lua/plugins/stockflow.lua:1072-1075, hack/scripts/internal/quickfort/stockflow.lua:636-640, hack/scripts/workorder.lua:190-191), and job.order_id is a ref-target back to manager_order.id - so duplicate/zero ids break the order-to-job linkage. Note that both shipped paths deliberately leave status.validated = false and status.active = false and let DF flip them (workorder.lua:278-279 even comments the fields out: "ignoring"), so those bits are not what we are missing; the id is. That belongs to the add_workorder_conditional lane but it is the thing that will still be broken after MANAGER is seated.

Is a BOOKKEEPER separately needed for stock counts to be exact? For the game's screens yes, for our scorer no, for work-order conditions probably not.
- The raw: BOOKKEEPER carries [RESPONSIBILITY:ACCOUNTING] and [REQUIRED_OFFICE:1], described as "keeps an accurate count of items in the fortress. They work in their office to improve the precision of the count." Position token wiki: the holder "will use the record keeper skill to keep track of stocks."
- The precision 1-5 dial is a nobles-screen setting (the interface raws ship NOBLES_ACCOUNTING_1..5 ACTIVE/INACTIVE sprites, seen in .codex-tmp/df_raws/vanilla_interface/graphics/graphics_classic.txt:1736+). Bookkeeper wiki: "To increase above the lowest level of accuracy, the bookkeeper needs a meager office", and the setting "only affects the accuracy of the count of items". I could NOT locate the struct field that holds the precision value - df.plotinfost.xml 404s on the df-structures mirror and nothing in the shipped Lua or docs mentions it. That is an open hole: assign_noble(BOOKKEEPER) will seat the dwarf but leave precision at tier 1 until we find that field or drive the nobles screen. UNRESOLVED.
- Our own observables do not go through the bookkeeper at all: bonsai-observe.lua:19-24 counts df.global.world.items.all by df.item_type.DRINK/FOOD directly, so the "drink 12 to 0" number is ground truth regardless of who is bookkeeping.
- Whether work-order item_conditions read real counts or bookkeeper records: INFERRED that they read real counts. No shipped code proves it; the supporting evidence is a player report of a condition counting far more thread than the stocks screen showed (https://steamcommunity.com/app/975370/discussions/0/3761101693160178924/), i.e. the condition seeing past the display. Cheap way to settle it on our save: queue one conditional order keyed on DRINK below N with no bookkeeper seated, and compare when it activates against the real DRINK count from world.items.all.

Practical ordering for the fort: assign_noble(MANAGER) and assign_noble(BOOKKEEPER) are both legal on the pinned save immediately - both are [APPOINTED_BY:EXPEDITION_LEADER], that seat is filled, and neither carries [REQUIRES_POPULATION] (unlike CAPTAIN_OF_THE_GUARD and DUNGEON_MASTER, which need 50). Seat MANAGER early and give it an office early, because the 20-resident cliff arrives mid-year with no warning and the failure is silent: orders simply stop turning into jobs.

WHAT I COULD NOT VERIFY. Everything here was read from shipped files or the DFHack source; nothing was executed, per the read-only rule. The three things a live run should check first: (a) that entity_position_assignment.flags needs no write on our pre-created vacant slots, (b) that history_event_add_hf_entity_linkst accepts a position_id field in this build - it is pcall'd, (c) the bookkeeper precision field.

RELEVANT ABSOLUTE PATHS
  D:\side_projects\bonsai_dwarf_fortress\lab_agent\bonsai_lab_agent\dfhack\bonsai-apply-actions.lua
  /srv/df-bonsai/current/hack/scripts/make-monarch.lua
  /srv/df-bonsai/current/hack/scripts/internal/emigration/unit-link-utils.lua
  /srv/df-bonsai/current/hack/scripts/bonsai-probe-mgr.lua
  /srv/df-bonsai/current/data/vanilla/vanilla_entities/objects/entity_default.txt
  /srv/df-bonsai/current/hack/docs/docs/dev/Lua API.txt
  /srv/df-bonsai/current/hack/lua/plugins/stockflow.lua
  /srv/df-bonsai/current/hack/scripts/workorder.lua

---

## `build_farm_plot(width, height)`  [confirmed]

```lua
-- ============================================================ build_farm_plot
-- Farm plots take NO materials. dfhack/buildings.lua has
--   [df.building_type.FarmPlot] = { }
-- so getFiltersByType returns an EMPTY table and constructBuilding routes to
-- constructWithFilters(instance, {}). That is not just tolerated, it is required:
-- Buildings.cpp asserts CHECK_INVALID_ARGUMENT(!items.empty() == needsItems(bld))
-- and needsItems() is false for FarmPlot. Passing a filter list will throw.
--
-- Add to the counter table at the top of bonsai-apply-actions.lua:
--   build_farm_plot = 0, set_crop = 0,

local TTA   = df.tiletype.attrs
local SHAPE = df.tiletype_shape
local TMAT  = df.tiletype_material

local SOIL_MATS = {
    [TMAT.SOIL] = true, [TMAT.GRASS_LIGHT] = true, [TMAT.GRASS_DARK] = true,
    [TMAT.GRASS_DRY] = true, [TMAT.GRASS_DEAD] = true, [TMAT.PLANT] = true,
}

-- quickfort's has_mud(), tightened to the single tile. The shipped version only
-- asks whether the enclosing 16x16 BLOCK carries any mud spatter event, which is
-- true for a whole block as soon as one puddle dries anywhere in it.
local function has_mud(x, y, z)
    local blk = dfhack.maps.getTileBlock(x, y, z)
    if not blk then return false end
    for _, ev in ipairs(blk.block_events) do
        if ev:getType() == df.block_square_event_type.material_spatter
           and ev.mat_type  == df.builtin_mats.MUD
           and ev.mat_state == df.matter_state.Solid then
            local ok, amt = pcall(function() return ev.amount[x % 16][y % 16] end)
            if not ok then return true end          -- fall back to block granularity
            if amt > 0 then return true end
        end
    end
    return false
end

-- is_valid_tile_farm() from quickfort, PLUS the three things DFHack's own
-- checkFreeTiles() does not test: hidden, tile material, and daylight.
local function farmable_tile(x, y, z, want_sub)
    if not dfhack.maps.isValidTilePos(x, y, z) then return false end
    local des, occ = dfhack.maps.getTileFlags(x, y, z)
    if not des then return false end
    if des.hidden then return false end             -- undug rock reads as "free"
    if occ.building ~= 0 then return false end      -- already a building here
    if des.flow_size > 0 then return false end
    if want_sub then
        -- every farmable cave crop is [BIOME:SUBTERRANEAN_WATER]; a lit tile can
        -- never grow one, and DF makes that loss permanent once sun has touched it
        if not des.subterranean or des.outside or des.light then return false end
    end
    local tt = dfhack.maps.getTileType(x, y, z)
    if not tt then return false end
    local at = TTA[tt]
    if SHAPE.attrs[at.shape].basic_shape ~= df.tiletype_shape_basic.Floor then
        return false
    end
    if at.shape == SHAPE.BOULDER or at.shape == SHAPE.PEBBLES then return false end
    return SOIL_MATS[at.material] == true or has_mud(x, y, z)
end

local function rect_farmable(x0, y0, z, w, h, want_sub)
    for dx = 0, w - 1 do
        for dy = 0, h - 1 do
            if not farmable_tile(x0 + dx, y0 + dy, z, want_sub) then return false end
        end
    end
    return true
end

-- verb body
elseif verb == "build_farm_plot" then
    pcall(function()
        local w = math.max(1, math.min(10, tonumber(a[2]) or 6))
        local h = math.max(1, math.min(10, tonumber(a[3]) or 3))
        local x, y, z = find_farm_site(w, h)        -- see the site-chooser contract
        if not x then
            print("APPLY build_farm_plot no-legal-site")
            return
        end
        local ok, b, err = pcall(dfhack.buildings.constructBuilding, {
            type  = df.building_type.FarmPlot,
            pos   = { x = x, y = y, z = z },
            width = w, height = h,
            full_rectangle = true,   -- abort rather than silently shrink the footprint
        })
        if not ok or not b then
            print("APPLY build_farm_plot fail " .. tostring(b or err))
            return
        end
        -- fallow every season slot; do NOT trust the allocator to have left -1 there
        for i in ipairs(b.plant_id) do b.plant_id[i] = -1 end
        c.build_farm_plot = c.build_farm_plot + 1
        -- THE side effect the game will not supply for you (see side_effect field)
        for _, u in ipairs(cits) do u.status.labors[df.unit_labor.PLANT] = true end
        df.global.process_jobs = true
    end)
```

**Side effect.** DFHack supplies the engine-facing half for you and this is the one place where that is true. constructBuilding -> constructWithFilters -> linkForConstruct calls linkBuilding (assigns building_next_id, pushes onto world.buildings.all, categorises into world.buildings.other.FARM_PLOT, stamps occupancy.building on every footprint tile), then creates a real df.job of type ConstructBuilding at the building centre, links it into world.jobs.list and into bld.jobs, and finally sets df.global.buildings_do_onupdate = true. So there is no dig-style 'flags.designated' trap here. The side effect you MUST add yourself is a labourer: constructing/preparing a farm plot and sowing it are both the Farming (Fields) labour, df.unit_labor.PLANT. With no citizen carrying it the ConstructBuilding job sits in world.jobs.list forever, bld.flags.exists never flips, and the plot is a decoration. df.global.process_jobs = true is cheap insurance, not a requirement.

**Observable.** Immediately: #df.global.world.buildings.other.FARM_PLOT rises by exactly one; the new b has b.x1,b.y1 == the requested corner, b.x2-b.x1+1 == w, b.y2-b.y1+1 == h, and b.room.extents == nil (a full rectangle needs no extents -- if extents are non-nil, checkFreeTiles carved tiles out and full_rectangle should have caught it); #b.jobs == 1 with b.jobs[0].job_type == df.job_type.ConstructBuilding. After a few thousand ticks: b.flags.exists == true. If exists stays false the whole episode, the cause is one of (a) nobody has df.unit_labor.PLANT, (b) the site is unreachable, (c) the job got cancelled. Cross-check with dfhack.maps.getTileFlags(b.centerx,b.centery,b.z).subterranean == true, which is what decides whether cave crops are even offered.

**Source.** /srv/df-bonsai/current/hack/lua/dfhack/buildings.lua (building_inputs[df.building_type.FarmPlot] = { }; constructBuilding body). /srv/df-bonsai/current/hack/scripts/internal/quickfort/build.lua:65-103 (is_valid_tile_dirt / is_floor / has_mud / is_valid_tile_farm), :844-850 (farm db entry: has_extents, no_extents_if_solid, is_valid_tile_fn=is_valid_tile_farm), :1259 (the constructBuilding call). /srv/df-bonsai/current/hack/scripts/build-now.lua:325 (FarmPlot is the documented zero-item building). '/srv/df-bonsai/current/hack/docs/docs/dev/Lua API.txt':2415 (setSize contract). https://raw.githubusercontent.com/DFHack/dfhack/develop/library/modules/Buildings.cpp (needsItems, checkFreeTiles, linkForConstruct). https://dwarffortresswiki.org/index.php/Farm_plot (soil-or-muddied-rock; Farming (Fields) labour for both preparing and planting).

**Gotcha.** Three traps, in order of how quietly they kill you. (1) DFHack does NOT validate the ground. Buildings::checkFreeTiles tests only: block exists, occupancy.building, HighPassable(tiletype), and liquid depth. It never reads tile material, never checks mud, and never checks designation.hidden. constructBuilding will happily return a farm plot on bare stone or on undug rock, the counter goes up, and nothing ever grows. All soil/mud validation is yours. (2) The plot is EXTENT-SHAPED. If any tile in the rectangle is blocked, checkFreeTiles allocates room.extents and carves that tile out instead of failing -- you get a smaller, oddly shaped plot with no error. full_rectangle = true is what turns that into a clean nil,err. (3) Reusing the existing site(n, radius) ring helper is a guaranteed dead farm: it returns u1.pos.z, the surface. Every farmable cave crop in the raws is [BIOME:SUBTERRANEAN_WATER] and cannot be sown on an above-ground tile, so a surface plot on perfectly good grass accepts none of the fort's seeds.

---

## `find_farm_site(width, height)  [trusted-side placement, not an agent verb]`  [inferred]

```lua
-- ======================================================= automatic placement
-- The agent never names coordinates. Anchor on the fort's own geometry: the
-- staircase head that designate_dig already pins in _G.BONSAI_PLACE.dig, which
-- is the only durable landmark we have (citizen[1] wanders -- that already cost
-- us an episode of orphaned dig designations).
--
-- Search order is deliberate: DOWN first, outward second. The seeds a fort holds
-- at embark are cave crops, so an underground soil floor is the only site that
-- can actually be sown. The surface pass is a last resort for a fort that has
-- somehow acquired above-ground seeds.

local function ring_offsets(r)
    local t = {}
    for dx = -r, r do
        for dy = -r, r do
            if math.max(math.abs(dx), math.abs(dy)) == r then t[#t+1] = {dx, dy} end
        end
    end
    return t
end

local function find_farm_site(w, h)
    local ax, ay, az
    if P.dig then
        ax, ay, az = P.dig[1], P.dig[2], P.dig[3]      -- pinned staircase head
    elseif u1 then
        ax, ay, az = u1.pos.x, u1.pos.y, u1.pos.z
    else
        return nil
    end
    local from = u1 and u1.pos or nil

    local function try(x0, y0, z, want_sub)
        if not rect_farmable(x0, y0, z, w, h, want_sub) then return false end
        -- keep the staircase column itself walkable: never straddle the shaft
        if z ~= az and ax >= x0 and ax < x0 + w and ay >= y0 and ay < y0 + h then
            return false
        end
        if from then
            -- advisory only: the walkability cache is refreshed while UNPAUSED, so
            -- a corridor dug during this same paused batch can read as unreachable
            local ok, reach = pcall(dfhack.maps.canWalkBetween, from,
                                    xyz2pos(x0, y0, z))
            if ok and not reach then
                local g = dfhack.maps.getWalkableGroup(xyz2pos(x0, y0, z))
                if not g or g == 0 then return false end
            end
        end
        return true
    end

    -- pass 1: subterranean, z descending from the landing just below the shaft head
    for dz = 1, 14 do
        for r = 1, 12 do
            for _, d in ipairs(ring_offsets(r)) do
                local x0, y0 = ax + d[1] - math.floor(w/2), ay + d[2] - math.floor(h/2)
                if try(x0, y0, az - dz, true) then return x0, y0, az - dz end
            end
        end
    end
    -- pass 2: the surface, above-ground crops only
    for r = 2, 14 do
        for _, d in ipairs(ring_offsets(r)) do
            local x0, y0 = ax + d[1] - math.floor(w/2), ay + d[2] - math.floor(h/2)
            if try(x0, y0, az, false) then return x0, y0, az end
        end
    end
    return nil
end
```

**Side effect.** None needed -- this is pure inspection. But it needs a precondition the dispatcher must not paper over: on turn 1 of an episode nothing is dug yet, so there is no subterranean soil floor and find_farm_site correctly returns nil. Report 'no-legal-site' and let the verb be retried on a later round rather than falling back to the surface ring; falling back is what produces a plot that can never be sown.

**Observable.** Log the chosen (x,y,z) plus dfhack.maps.getTileFlags(x,y,z).subterranean and df.tiletype_material[df.tiletype.attrs[dfhack.maps.getTileType(x,y,z)].material]. A healthy pick reads subterranean=true, material=SOIL, z strictly below the pinned shaft head. If you see subterranean=false or material=STONE/LAVA_STONE, the chooser is broken and every crop written afterwards will be a no-op. Also assert occupancy.building == 0 on all w*h tiles BEFORE constructing -- after constructing, those same tiles must read non-zero, which is the cheapest proof that linkBuilding ran.

**Source.** Composed from confirmed pieces: quickfort is_valid_tile_farm (/srv/df-bonsai/current/hack/scripts/internal/quickfort/build.lua:102); autofarm's subterranean test Maps::getTileDesignation(centerx,centery,z)->bits.subterranean; '/srv/df-bonsai/current/hack/docs/docs/dev/Lua API.txt':2233-2241 (getWalkableGroup / canWalkBetween, including the note that the pathfinding cache is only updated while unpaused); the existing P.dig anchor in D:\side_projects\bonsai_dwarf_fortress\lab_agent\bonsai_lab_agent\dfhack\bonsai-apply-actions.lua:61-121. The search order and the shaft-straddle guard are my design, not read from shipped code.

**Gotcha.** canWalkBetween reads a cache DF only refreshes while unpaused, and our dispatcher runs paused. Treating it as a hard gate can reject a perfectly good site one step after the corridor was dug, and treating it as absent lets you build a farm nobody can reach. Hence advisory + getWalkableGroup fallback. Second: soil-layer farm tiles outside the caverns are rated 'poor' and lose 75% of their yield versus muddied stone in a stone layer -- correct but slow, so a first-year fort should get a larger plot rather than a cleverer one. Third: do not add a placement cursor like P.stock. It is unnecessary here and was itself a workaround -- a built or planned plot stamps occupancy.building on its tiles, so the very next search skips it for free.

---

## `set_crop(season, plant)`  [confirmed]

```lua
-- ==================================================================== set_crop
-- The field is building_farmplotst.plant_id: a four-element static array of
-- int16_t, index-enum 'season' (Spring=0 Summer=1 Autumn=2 Winter=3), ref-target
-- plant_raw. The value is the PLANT RAW INDEX -- the same integer as a seed
-- item's mat_index and as plant_raw.index. -1 means fallow. autofarm does
-- literally one write: farm->plant_id[season] = new_plant_id.

local SEASON_FLAG = { [0] = 'SPRING', [1] = 'SUMMER', [2] = 'AUTUMN', [3] = 'WINTER' }
local SEASON_ARG  = { spring = 0, summer = 1, autumn = 2, fall = 2, winter = 3 }

-- autofarm.cpp find_plantable_plants(): a seed stack only counts if none of these
-- item flags are set. in_building is what excludes seeds already sown in a plot.
local SEED_BAD = { 'dump', 'forbid', 'garbage_collect', 'hostile', 'on_fire',
                   'rotten', 'trader', 'in_building', 'construction', 'artifact' }

local function seed_stock()
    local n = {}
    for _, s in ipairs(df.global.world.items.other.SEEDS) do
        local bad = false
        for _, k in ipairs(SEED_BAD) do if s.flags[k] then bad = true break end end
        if not bad then
            n[s.mat_index] = (n[s.mat_index] or 0) + s.stack_size
        end
    end
    return n
end

-- The four slots, discovered rather than assumed: DFHack indexes an enum-indexed
-- static array by ENUM VALUE, and 'season' also carries None = -1. ipairs on a
-- DFHack container yields the true index range, so this cannot go off by one.
local function season_slots(b)
    local s = {}
    for i in ipairs(b.plant_id) do s[#s + 1] = i end   -- {0,1,2,3} in this build
    return s
end

local function plot_biome_flag(b)
    local des = dfhack.maps.getTileFlags(b.centerx, b.centery, b.z)
    local bt
    if des and des.subterranean then
        bt = df.biome_type.SUBTERRANEAN_WATER          -- exactly what autofarm does
    else
        local rx, ry = dfhack.maps.getTileBiomeRgn(b.centerx, b.centery, b.z)
        bt = dfhack.maps.getBiomeType(rx, ry)
    end
    return df.biome_type.attrs[bt].plant_raw_flags     -- e.g. BIOME_SUBTERRANEAN_WATER
end

-- autofarm.cpp is_plantable(), minus its harvest-date look-ahead
local function plantable(p, season_idx, biome_flag)
    if not p.flags.SEED then return false end
    if p.flags.TREE then return false end
    if not p.flags[SEASON_FLAG[season_idx]] then return false end
    return p.flags[biome_flag] and true or false
end

local function find_plant(name)
    local want = string.upper(name or '')
    local all = df.global.world.raws.plants.all
    for i, p in ipairs(all) do
        if string.upper(p.id) == want then return i, p end
    end
    for i, p in ipairs(all) do
        if string.find(string.upper(p.id), want, 1, true) then return i, p end
    end
    return nil
end

-- verb body
elseif verb == "set_crop" then
    pcall(function()
        local sa = string.lower(a[2] or 'all')
        local seasons
        if sa == 'all' then seasons = { 0, 1, 2, 3 }
        elseif SEASON_ARG[sa] then seasons = { SEASON_ARG[sa] }
        else return end

        local plots = df.global.world.buildings.other.FARM_PLOT
        if #plots == 0 then print("APPLY set_crop no-plots") return end
        local stock = seed_stock()
        local all   = df.global.world.raws.plants.all

        for _, b in ipairs(plots) do
            local bflag = plot_biome_flag(b)
            local slots = season_slots(b)
            for _, s in ipairs(seasons) do
                local idx = nil
                if a[3] and string.lower(a[3]) ~= 'best' then
                    local i, p = find_plant(a[3])
                    -- refuse a crop this plot cannot actually grow this season
                    if i and stock[i] and plantable(p, s, bflag) then idx = i end
                end
                if not idx then                 -- fall back to the seed we hold most of
                    local best = -1
                    for mi, cnt in pairs(stock) do
                        local q = all[mi]
                        if q and plantable(q, s, bflag) and cnt > best then
                            best, idx = cnt, mi
                        end
                    end
                end
                if idx then
                    b.plant_id[slots[s + 1]] = idx
                    c.set_crop = c.set_crop + 1
                end
            end
        end
        df.global.process_jobs = true      -- insurance; autofarm does not bother
    end)
```

**Side effect.** None needed. This is the one contract in the set where the plain write is genuinely enough: autofarm is a shipped, enabled-by-players plugin whose entire crop-assignment path is 'farm->plant_id[season] = new_plant_id' with no flag poke, no job push, no dirty bit -- DF re-reads the plot in its own building update. What has to be true instead is a set of preconditions, and each one is a silent failure if missed: the plot must be BUILT (b.flags.exists), some citizen must carry df.unit_labor.PLANT, the seeds must exist unforbidden and reachable, and the chosen plant must be legal for the plot's biome and the season being written. Also: cooking destroys seeds, so set_kitchen_flag must forbid cooking the crop or the seed supply is a one-shot.

**Observable.** Immediately, read straight back: for _,b in ipairs(df.global.world.buildings.other.FARM_PLOT) do for i,v in ipairs(b.plant_id) do print(i, v, v >= 0 and df.global.world.raws.plants.all[v].id or 'FALLOW') end end. All four slots should name the intended raw id, and specifically must NOT read 0/SINGLE-GRAIN_WHEAT, which is what an unwritten slot looks like. Then, over ticks: a df.job_type.PlantSeeds job appears in df.global.world.jobs.list holding the plot; the free seed count from seed_stock() falls while seeds with flags.in_building == true show up in b.contained_items with use_mode == df.building_item_role_type.PERM; and finally #df.global.world.items.other.PLANT / PLANT_GROWTH rises. If plant_id is set correctly and no PlantSeeds job ever appears, the fault is labour, reachability, or the plot never finished building -- not this field.

**Source.** https://raw.githubusercontent.com/DFHack/dfhack/develop/plugins/autofarm.cpp (set_farm: farm->plant_id[season] = new_plant_id, -1 to fallow; is_plantable: SEED flag set, TREE clear, season flag set, biomeFlagMap; find_plantable_plants: scan world.items.other[SEEDS], bad_flags mask, counts[i->mat_index] += stack_size; process(): subterranean designation on the plot centre => biome_type::SUBTERRANEAN_WATER). https://raw.githubusercontent.com/DFHack/df-structures/master/df.building.xml (building_farmplotst: static-array plant_id, original-name 'plant', index-enum 'season', int16_t ref-target plant_raw; plus farm_flags/last_season/current_fertilization/max_fertilization/terrain_purge_timer). https://raw.githubusercontent.com/DFHack/df-structures/master/df.matgloss.xml (plant_raw_flags enum: SPRING SUMMER AUTUMN WINTER BUNDLE SEED ... TREE ...; plant_raw.index, plant_raw.flags is a df-flagarray indexed by that enum). /srv/df-bonsai/current/hack/lua/plugins/seedwatch.lua (seed counts keyed by plant index, printed as plants[k].id). /srv/df-bonsai/current/hack/scripts/growcrops.lua (crops[idx] built from ipairs(world.raws.plants.all) and looked up by seed.mat_index -- proves plant index == seed mat_index and that DFHack ipairs is 0-based). /srv/df-bonsai/current/hack/scripts/modtools/extra-gamelog.lua:10-15 (season 0=Spring 1=Summer 2=Autumn 3=Winter). Container raws /srv/df-bonsai/current/data/vanilla/vanilla_plants/objects/plant_standard.txt (MUSHROOM_HELMET_PLUMP: [SPRING][SUMMER][AUTUMN][WINTER][BIOME:SUBTERRANEAN_WATER][GROWDUR:300]; GRASS_TAIL_PIG: [SUMMER][AUTUMN] only). DFHack news.rst:1963 (biome_type gained enum attrs 'caption' and 'plant_raw_flags').

**Gotcha.** Four. (1) A freshly DFHack-allocated plot's plant_id may be zero-filled rather than -1, and plant raw index 0 in this install is SINGLE-GRAIN_WHEAT (plant_crops.txt loads before plant_standard.txt) -- an above-ground tropical grassland cereal. An unwritten slot therefore looks like a valid crop and grows nothing. That specific claim is INFERRED, not read from shipped code; the build_farm_plot contract fallows all four slots defensively so it cannot bite. (2) Season is not free. Pig tail is [SUMMER][AUTUMN] only -- write it into the Spring slot and that quarter of the year is dead. Plump helmet is the only cave crop with all four season flags, which is exactly why the guide calls it the staple. (3) plant_id is int16_t, index-enum 'season', and the season enum also has None = -1. Do not hardcode numeric 0..3 on faith; season_slots() derives the real index range from ipairs so the array base can never bite you. (4) The value is the PLANT index, not a material index and not a seed item subtype -- df.global.world.raws.plants.all[v], never dfhack.matinfo. Writing a mat_type there produces a plausible-looking number and a plot that grows the wrong thing or nothing.

---

**Lane notes.** WHAT DF ACTUALLY REQUIRES UNDER A FARM PLOT (confirmed, quickfort build.lua:65-103 + wiki):
soil OR mud-covered floor. Precisely: tiletype_material in {SOIL, GRASS_LIGHT, GRASS_DARK, GRASS_DRY, GRASS_DEAD, PLANT}, OR any floor whose block carries a solid MUD material_spatter. Shape must be basic_shape Floor and must not be BOULDER/PEBBLES/WALL. Not hidden, no building occupancy, no standing liquid. It does NOT need to be indoors -- the wiki is explicit that "the attributes Inside, Outside are of no relevance". What matters is Above Ground vs Subterranean (designation.subterranean), because that alone decides which crop list the plot gets.

SIZE is specified as plain width/height on constructBuilding; getCorrectSize puts FarmPlot in the caller-chooses-size branch alongside Bridge/Road/Stockpile, so there is no fixed dimension to fight. Pass full_rectangle = true. Non-rectangular plots are possible by writing fields.room = {x,y,width,height,extents=<uint8 array>} before setSize, which is how quickfort does irregular farms, but quickfort deliberately skips extents entirely when the rectangle is solid (no_extents_if_solid=true) and so should we.

THE THING THAT ACTUALLY EXPLAINS THE MEASURED YEAR. The catalog's build_workshop places on a ring at u1.pos.z -- the surface. Every farmable cave crop in this install's raws (MUSHROOM_HELMET_PLUMP, GRASS_TAIL_PIG, GRASS_WHEAT_CAVE, MUSHROOM_CUP_DIMPLE, POD_SWEET, BUSH_QUARRY) is [BIOME:SUBTERRANEAN_WATER]. If build_farm_plot inherits that ring helper, the fort gets a legally-constructed plot on grass that can be assigned no crop it owns seeds for, the verb counter increments, and drink still goes 12 to 0. Placement must go DOWN, anchored on the pinned staircase head, or the verb is theatre.

CROSS-LANE DEPENDENCIES worth flagging to whoever owns the other three verbs:
- df.unit_labor.PLANT (Farming (Fields), Planter skill) gates BOTH constructing/preparing the plot and sowing it. Nothing in this lane works without it. The existing set_labor verb can supply it, but the agent has to think of it; I would have build_farm_plot set it unconditionally, as in the Lua above, on the same reasoning that the dig verb sets process_dig.
- set_kitchen_flag matters more than it looks: cooking a plant yields no seed, so an unprotected plump helmet crop is a one-generation crop. seedwatch (shipped, C++) exists precisely for this and its threshold default is 30.
- Harvesting is unskilled and open to anyone by default, so no labour is needed on that end.

TWO SHIPPED TOOLS THAT DO 80% OF THIS ALREADY, if you would rather borrow than build: `enable autofarm` reassigns crops on every plot every ~53 frames based on which plant stocks are below threshold (default 50), and `enable seedwatch` auto-protects seeds from cookery. Both are C++ plugins present in /srv/df-bonsai/current/hack/plugins. That is a legitimate alternative contract for set_crop -- but it hands the decision to DFHack rather than the agent, which defeats the measurement, so I have written the contracts for doing it ourselves.

THINGS I COULD NOT CONFIRM AND DID NOT GUESS AT:
- Whether df.building_farmplotst's plant_id comes out of dfhack.buildings.allocInstance as 0 or -1. Marked inferred, defended against.
- The exact field name of the per-tile mud quantity on block_square_event_material_spatterst (I use ev.amount[x%16][y%16] behind a pcall that degrades to quickfort's block-granularity behaviour). Note that quickfort's own has_mud has this imprecision and ships with it.
- Whether the pinned save's dwarves actually carry seeds, and which. Nothing in the measured facts says. seed_stock() reads it at runtime and the 'best' fallback makes the verb behave sanely either way, but it is worth one probe: for _,s in ipairs(df.global.world.items.other.SEEDS) do print(df.global.world.raws.plants.all[s.mat_index].id, s.stack_size) end.

FILES: dispatcher to edit is D:\side_projects\bonsai_dwarf_fortress\lab_agent\bonsai_lab_agent\dfhack\bonsai-apply-actions.lua (add build_farm_plot and set_crop to the counter table at line 13, add the helpers above the `for line in f:lines()` loop at line 40). Signatures already declared at D:\side_projects\bonsai_dwarf_fortress\lab_agent\bonsai_lab_agent\actions\catalog.py:128-155 and match these contracts exactly (width/height 1..10 default 6x3; season enum spring|summer|autumn|winter|all; plant as a raw id string).

---
