-- Why is nobody taking the dig jobs?
--
-- Reports the two things a miner needs before a dig job can be claimed: a pick it can
-- walk to, and a job site it can walk to. Written after the obvious answer turned out to
-- be wrong — every pick on this fort carries flags.foreign, another civilisation's
-- property, and clearing it changed nothing: 14 dig jobs, 23 miners, still zero workers.

local w = df.global.world
local P = _G.BONSAI_PLACE
local u = dfhack.units.getCitizens(true)[1]
if not (u and P and P.dig) then print('no citizen or no pinned shaft'); return end

local ox, oy, oz = P.dig[1], P.dig[2], P.dig[3]
print(string.format('dwarf %d at %d,%d,%d   shaft head %d,%d,%d',
    u.id, u.pos.x, u.pos.y, u.pos.z, ox, oy, oz))

local function walkable(to)
    local ok, r = pcall(function() return dfhack.maps.canWalkBetween(u.pos, to) end)
    return ok and tostring(r) or 'ERR'
end

print('walk dwarf -> shaft head: ' .. walkable(xyz2pos(ox, oy, oz)))

for _, i in ipairs(w.items.all) do
    if i:getType() == df.item_type.WEAPON then
        local st = df.itemdef_weaponst.find(i:getSubtype())
        if st and st.id == 'ITEM_WEAPON_PICK' then
            local hu
            pcall(function() hu = dfhack.items.getHolderUnit(i) end)
            local fl = {}
            for k, v in pairs(i.flags) do
                if v == true then fl[#fl + 1] = k end
            end
            table.sort(fl)
            print(string.format('pick %d at %d,%d,%d unit=%s reachable=%s flags=[%s]',
                i.id, i.pos.x, i.pos.y, i.pos.z, hu and tostring(hu.id) or 'none',
                walkable(xyz2pos(i.pos.x, i.pos.y, i.pos.z)), table.concat(fl, ',')))
        end
    end
end

local shown = 0
local link = w.jobs.list.next
while link and shown < 4 do
    local j = link.item
    local n = j and tostring(df.job_type[j.job_type]) or ''
    if n:match('Dig') or n:match('Carve') then
        shown = shown + 1
        local fl = {}
        for k, v in pairs(j.flags) do
            if v == true then fl[#fl + 1] = k end
        end
        table.sort(fl)
        -- reachable=false on an UNDUG wall is normal, not a diagnosis: you cannot walk
        -- into rock. What matters is whether the tile ABOVE or beside it can be reached,
        -- which is what the staircase provides.
        print(string.format('digjob %-24s at %d,%d,%d reachable=%s posting=%s flags=[%s]',
            tostring(df.job_type[j.job_type]), j.pos.x, j.pos.y, j.pos.z,
            walkable(j.pos), tostring(j.posting_index), table.concat(fl, ',')))
    end
    link = link.next
end

-- What the miners are doing instead
local doing = {}
for _, cit in ipairs(dfhack.units.getCitizens(true)) do
    if cit.status.labors[df.unit_labor.MINE] then
        local jb = cit.job.current_job
        local k = jb and tostring(df.job_type[jb.job_type]) or 'idle'
        doing[k] = (doing[k] or 0) + 1
    end
end
local parts = {}
for k, v in pairs(doing) do parts[#parts + 1] = k .. '=' .. v end
table.sort(parts)
print('miners are doing: ' .. table.concat(parts, ' '))
