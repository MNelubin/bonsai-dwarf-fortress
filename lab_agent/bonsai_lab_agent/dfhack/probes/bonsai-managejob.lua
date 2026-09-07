-- Create the manager's ManageWorkOrders job by hand and post it at the office.
--
-- DF schedules this job itself when plotinfo.nobles.manager_cooldown reaches 0 and it
-- finds an officeholder. On our scripted-embark saves that check fails for reasons that
-- have survived a long elimination (population, office, seating fields, squad
-- membership, fort age, rank, progress, save_progress, site links all ruled out), while
-- the cooldown itself decrements at the normal 1-per-10-ticks. So: build the job the
-- game would have built, and let the manager work it.

local w = df.global.world

local mgr
for _, u in ipairs(dfhack.units.getCitizens(true)) do
    for _, np in ipairs(dfhack.units.getNoblePositions(u) or {}) do
        if np.position.code == 'MANAGER' then mgr = u end
    end
end
if not mgr then print('MANAGEJOB no manager'); return end

-- the office the manager owns, and the chair inside it: the job is done sitting down
local office
for _, b in ipairs(mgr.owned_buildings) do
    if b:getType() == df.building_type.Civzone
        and b:getSubtype() == df.civzone_type.Office then office = b end
end
if not office then print('MANAGEJOB no office owned'); return end

local chair
for _, b in ipairs(w.buildings.all) do
    if b:getType() == df.building_type.Chair and b.z == office.z
        and b.x1 >= office.x1 and b.x1 <= office.x2
        and b.y1 >= office.y1 and b.y1 <= office.y2 then chair = b end
end
if not chair then print('MANAGEJOB no chair in office'); return end

for _, j in ipairs(chair.jobs) do
    if j.job_type == df.job_type.ManageWorkOrders then
        print('MANAGEJOB already queued', j.id); return
    end
end

local job = df.job:new()
job.job_type = df.job_type.ManageWorkOrders
job.pos = xyz2pos(chair.x1, chair.y1, chair.z)
job.flags.special = true
dfhack.job.linkIntoWorld(job, true)

local ref = df.general_ref_building_holderst:new()
ref.building_id = chair.id
job.general_refs:insert('#', ref)
chair.jobs:insert('#', job)

print(string.format('MANAGEJOB created id=%d at %d,%d,%d manager=%d chair=%d office=%d',
    job.id, job.pos.x, job.pos.y, job.pos.z, mgr.id, chair.id, office.id))
