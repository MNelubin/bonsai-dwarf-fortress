-- One line of digging state, for A/B-ing what actually stops a fort from excavating.
--
--   bonsai-digstat <tag>
--
-- Reports around the pinned shaft head, so it is comparable across runs: how much soil
-- floor exists (excavated), how many tiles still carry a designation (outstanding), how
-- many dig jobs exist and how many of them have somebody on them, and how many picks
-- the fort cannot use because they belong to another civilisation.

local tag = (...) or 'STAT'
local w = df.global.world
local P = _G.BONSAI_PLACE

local soil, marked = 0, 0
if P and P.dig then
    local ox, oy, oz = P.dig[1], P.dig[2], P.dig[3]
    for dz = 1, 8 do
        for dx = -8, 8 do
            for dy = -8, 8 do
                local x, y, z = ox + dx, oy + dy, oz - dz
                local okt, tt = pcall(function() return dfhack.maps.getTileType(x, y, z) end)
                if okt and tt then
                    local at = df.tiletype.attrs[tt]
                    if at.shape == df.tiletype_shape.FLOOR
                        and at.material == df.tiletype_material.SOIL then
                        soil = soil + 1
                    end
                end
                local okd, des = pcall(function() return dfhack.maps.getTileFlags(x, y, z) end)
                if okd and des and des.dig ~= df.tile_dig_designation.No then
                    marked = marked + 1
                end
            end
        end
    end
end

local jobs, worked = 0, 0
local link = w.jobs.list.next
while link do
    local j = link.item
    if j and tostring(df.job_type[j.job_type]):match('Dig') then
        jobs = jobs + 1
        if dfhack.job.getWorker(j) then worked = worked + 1 end
    end
    link = link.next
end

local picks, foreign = 0, 0
for _, i in ipairs(w.items.all) do
    if i:getType() == df.item_type.WEAPON then
        local st = df.itemdef_weaponst.find(i:getSubtype())
        if st and st.id == 'ITEM_WEAPON_PICK' then
            picks = picks + 1
            if i.flags.foreign then foreign = foreign + 1 end
        end
    end
end

local miners = 0
for _, u in ipairs(dfhack.units.getCitizens(true)) do
    if u.status.labors[df.unit_labor.MINE] then miners = miners + 1 end
end

print(string.format(
    '%-16s tick=%-7d soil_floors=%-4d designated=%-4d dig_jobs=%-3d with_worker=%-3d '
    .. 'picks=%d foreign=%d miners=%d',
    tag, df.global.cur_year_tick, soil, marked, jobs, worked, picks, foreign, miners))
