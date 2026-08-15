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
                if j.job_type == df.job_type.ProcessPlantsBarrel then return j, b end
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

local job = df.job:new()
job.job_type = df.job_type.ProcessPlantsBarrel
job.pos = xyz2pos(still.centerx, still.centery, still.z)
dfhack.job.addGeneralRef(job, df.general_ref_type.BUILDING_HOLDER, still.id)
still.jobs:insert('#', job)
dfhack.job.linkIntoWorld(job, true)

-- Answered by experiment: a job created bare is CANCELLED — DF does not fill job_items
-- in for us, so the specification has to be written. This one is built from DFHack's own
-- shipped condition for brewing, "at least 150 unrotten barrel-processable plants and at
-- least 5 empty barrels": one plant that is processable_to_barrel, and one empty barrel
-- to put the drink in.
local function spec(fields)
    local ji = df.job_item:new()
    ji.item_type = fields.item_type or -1
    ji.item_subtype = -1
    ji.mat_type = -1
    ji.mat_index = -1
    ji.quantity = 1
    ji.vector_id = fields.vector or df.job_item_vector_id.IN_PLAY
    for _, f in ipairs(fields.flags1 or {}) do ji.flags1[f] = true end
    for _, f in ipairs(fields.flags3 or {}) do ji.flags3[f] = true end
    job.job_items.elements:insert('#', ji)
end

spec { item_type = df.item_type.PLANT,
       flags1 = { 'unrotten', 'processable_to_barrel' } }
spec { item_type = df.item_type.BARREL, flags1 = { 'empty' } }

local specs = 0
pcall(function() specs = #job.job_items.elements end)
print(string.format('created BrewDrink job %d at the Still: specs=%d items=%d',
    job.id, specs, #job.items))

local plants, barrels, drink = 0, 0, 0
for _, i in ipairs(w.items.all) do
    local t = i:getType()
    if t == df.item_type.PLANT and not i.flags.rotten then plants = plants + 1 end
    if t == df.item_type.BARREL then barrels = barrels + 1 end
    if t == df.item_type.DRINK then drink = drink + 1 end
end
print(string.format('stock: plants=%d barrels=%d drink=%d', plants, barrels, drink))
