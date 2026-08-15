-- Does DF fill in a standard workshop job's requirements by itself?
--
-- Note the job type: there is no BrewDrink in df.job_type on this build. Brewing is
-- ProcessPlantsBarrel — plants that are processable_to_barrel, turned into drink in a
-- barrel — which is exactly what DFHack's shipped basic library orders, "while there are
-- at least 150 unrotten barrel-processable plants and at least 5 empty barrels".
--
-- Furniture jobs work either way: a pinned item or a specification both produce a bed.
-- Brewing and cooking cannot be done with a pinned item — a real PrepareMeal job carries
-- four flag-filtered requirements (unrotten, cookable) and no item type at all — and no
-- shipped order library contains a brewing order to copy. So rather than invent the
-- filter, ask the game: create the job bare and see what DF puts in it.
--
--   bonsai-brewprobe            create one bare BrewDrink job at a Still
--   bonsai-brewprobe report     print what DF made of it

local w = df.global.world
local mode = (...) or 'create'

local function find_brew()
    for _, b in ipairs(w.buildings.all) do
        if df.building_workshopst:is_instance(b) then
            for _, j in ipairs(b.jobs) do
                if j.job_type == df.job_type.CustomReaction
                    and tostring(j.reaction_name) == 'BREW_DRINK_FROM_PLANT' then return j, b end
            end
        end
    end
end

if mode == 'report' then
    local j, b = find_brew()
    if not j then print('BREW job is gone — DF cancelled it'); return end
    local specs = 0
    pcall(function() specs = #j.job_items.elements end)
    print(string.format('BREW job %d at %s: items=%d specs=%d worker=%s',
        j.id, tostring(df.workshop_type[b.type]), #j.items, specs,
        tostring(dfhack.job.getWorker(j) and dfhack.job.getWorker(j).id or 'none')))
    pcall(function()
        for _, ji in ipairs(j.job_items.elements) do
            local f = {}
            for _, fn in ipairs({ 'flags1', 'flags2', 'flags3' }) do
                for k, v in pairs(ji[fn]) do
                    if v == true then f[#f + 1] = k end
                end
            end
            table.sort(f)
            print(string.format('   need type=%s sub=%d mat=%d:%d qty=%d vec=%s flags=[%s]',
                tostring(df.item_type[ji.item_type]), ji.item_subtype,
                ji.mat_type, ji.mat_index, ji.quantity,
                tostring(df.job_item_vector_id[ji.vector_id]), table.concat(f, ',')))
        end
    end)
    for _, it in ipairs(j.items) do
        print('   holds ' .. tostring(df.item_type[it.item:getType()]))
    end
    return
end

local still
for _, b in ipairs(w.buildings.all) do
    if df.building_workshopst:is_instance(b) and b.type == df.workshop_type.Still then
        still = b
    end
end
if not still then print('no Still on this fort'); return end

-- Brewing is a REACTION on this build, not a job type. There is no BrewDrink in
-- df.job_type, and a ProcessPlantsBarrel job at a Still is cancelled — measured three
-- times with 102 plants and 15 barrels standing free. The raws carry
-- BREW_DRINK_FROM_PLANT and BREW_DRINK_FROM_PLANT_GROWTH, which is also why the
-- hand-played fort's food orders read `CustomReaction`.
local reaction, ridx
for i, r in ipairs(w.raws.reactions.reactions) do
    if tostring(r.code) == 'BREW_DRINK_FROM_PLANT' then reaction, ridx = r, i end
end
if not reaction then print('no BREW_DRINK_FROM_PLANT reaction'); return end

local job = df.job:new()
job.job_type = df.job_type.CustomReaction
job.reaction_name = reaction.code
job.pos = xyz2pos(still.centerx, still.centery, still.z)
dfhack.job.addGeneralRef(job, df.general_ref_type.BUILDING_HOLDER, still.id)
still.jobs:insert('#', job)
dfhack.job.linkIntoWorld(job, true)

-- Copy the reaction's OWN reagents rather than inventing a filter. DF does not fill
-- job_items in for a DFHack-created job — a bare one is cancelled — so the requirements
-- have to be written, and the reaction definition is where they already exist.
local copied = 0
for _, rg in ipairs(reaction.reagents) do
    local ok = pcall(function()
        local ji = df.job_item:new()
        ji.item_type = rg.item_type
        ji.item_subtype = rg.item_subtype
        ji.mat_type = rg.mat_type
        ji.mat_index = rg.mat_index
        ji.quantity = rg.quantity
        ji.vector_id = df.job_item_vector_id.IN_PLAY
        ji.reaction_id = ridx
        for _, fn in ipairs({ 'flags1', 'flags2', 'flags3' }) do
            for k, v in pairs(rg[fn]) do
                if v == true then ji[fn][k] = true end
            end
        end
        job.job_items.elements:insert('#', ji)
        copied = copied + 1
    end)
    if not ok then break end
end

print(string.format('created %s job %d at the Still: reagents copied=%d of %d',
    reaction.code, job.id, copied, #reaction.reagents))

local plants, barrels, drink = 0, 0, 0
for _, i in ipairs(w.items.all) do
    local t = i:getType()
    if t == df.item_type.PLANT and not i.flags.rotten then plants = plants + 1 end
    if t == df.item_type.BARREL then barrels = barrels + 1 end
    if t == df.item_type.DRINK then drink = drink + 1 end
end
print(string.format('stock: plants=%d barrels=%d drink=%d', plants, barrels, drink))
