-- Dump the fortress entity, the MANAGER position and its assignment, field by field,
-- for diffing one fort against another.
--
-- The plotinfo diff eliminated every fort-level scalar; the entity is the other place
-- DF could be reading "who is the manager" from. Same output shape as bonsai-plotdump:
-- sorted `key = value`, vectors reduced to a length, bitfields to their set bits.

local out = {}
local function p(k, v) out[#out + 1] = string.format('%s = %s', k, tostring(v)) end

local function dump(prefix, obj, typ, depth)
    depth = depth or 0
    if depth > 2 or not (typ and typ._fields) then return end
    local names = {}
    for k in pairs(typ._fields) do names[#names + 1] = k end
    table.sort(names)
    for _, k in ipairs(names) do
        local ok, v = pcall(function() return obj[k] end)
        if not ok then
            p(prefix .. k, 'ERR')
        elseif type(v) == 'number' or type(v) == 'boolean' or type(v) == 'string' then
            p(prefix .. k, v)
        elseif type(v) == 'userdata' then
            local okn, n = pcall(function() return #v end)
            if okn then
                p(prefix .. k .. '.n', n)
            else
                local okt, sub = pcall(function() return v._type end)
                if okt and sub then
                    dump(prefix .. k .. '.', v, sub, depth + 1)
                else
                    local bits, any = {}, false
                    pcall(function()
                        for bk, bv in pairs(v) do
                            any = true
                            if bv == true then bits[#bits + 1] = bk end
                        end
                    end)
                    if any then
                        table.sort(bits)
                        p(prefix .. k, '{' .. table.concat(bits, ',') .. '}')
                    end
                end
            end
        end
    end
end

local ent = df.global.plotinfo.main.fortress_entity
dump('entity.', ent, df.historical_entity)

local mp
for _, pos in ipairs(ent.positions.own) do
    if pos.code == 'MANAGER' then mp = pos end
end
if mp then
    dump('mgrpos.', mp, mp._type)
    for _, a in ipairs(ent.positions.assignments) do
        if a.position_id == mp.id then dump('mgrasg.', a, a._type) end
    end
end

-- the seated figure, one level deep: the unit-side half of the link is where the last
-- three bugs in this area lived
local hf
for _, a in ipairs(ent.positions.assignments) do
    if mp and a.position_id == mp.id and a.histfig ~= -1 then
        hf = df.historical_figure.find(a.histfig)
    end
end
if hf then
    dump('mgrhf.', hf, df.historical_figure)
    local u = df.unit.find(hf.unit_id)
    if u then
        p('mgrunit.id', u.id)
        for _, k in ipairs {'civ_id', 'population_id', 'profession', 'mood',
                            'hist_figure_id', 'race', 'caste'} do
            local ok, v = pcall(function() return u[k] end)
            p('mgrunit.' .. k, ok and v or 'ERR')
        end
        for _, k in ipairs {'flags1', 'flags2', 'flags3', 'flags4'} do
            local bits = {}
            pcall(function()
                for bk, bv in pairs(u[k]) do if bv == true then bits[#bits + 1] = bk end end
            end)
            table.sort(bits)
            p('mgrunit.' .. k, '{' .. table.concat(bits, ',') .. '}')
        end
        p('mgrunit.is_citizen', dfhack.units.isCitizen(u))
        p('mgrunit.squad_id', (u.military and u.military.squad_id) or -1)
    end
end

table.sort(out)
local port = os.getenv('DFHACK_PORT') or 'x'
local f = assert(io.open('/tmp/entdump.' .. port .. '.txt', 'w'))
f:write(table.concat(out, '\n'), '\n')
f:close()
print('wrote /tmp/entdump.' .. port .. '.txt lines=' .. #out)
