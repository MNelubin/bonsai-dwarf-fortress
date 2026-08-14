-- Dump every scalar field of plotinfo (and a few neighbouring fort-level structs) as
-- `key = value` lines, sorted, for diffing one fort against another.
--
-- Written after field-by-field guessing failed: on our scripted-embark fort DF's whole
-- manager/bookkeeper subsystem never executes — plotinfo.manager_timer does not even
-- decrement when written — while an identical order on a hand-played fort validates in
-- ~8,000 ticks. Rather than keep proposing single fields, dump them all and let diff
-- name the difference.

local out = {}
local function p(k, v) out[#out + 1] = string.format('%s = %s', k, tostring(v)) end

local function dump(prefix, obj, typ, depth)
    depth = depth or 0
    if depth > 2 then return end
    local fields = typ and typ._fields
    if not fields then return end
    local names = {}
    for k in pairs(fields) do names[#names + 1] = k end
    table.sort(names)
    for _, k in ipairs(names) do
        local ok, v = pcall(function() return obj[k] end)
        if not ok then
            p(prefix .. k, 'ERR')
        elseif type(v) == 'number' or type(v) == 'boolean' or type(v) == 'string' then
            p(prefix .. k, v)
        elseif type(v) == 'userdata' then
            -- vectors reduce to a length; nested compounds recurse one more level so
            -- bitfields and small sub-structs (flags, nobles, tasks) are covered
            local okn, n = pcall(function() return #v end)
            if okn then
                p(prefix .. k .. '.n', n)
            else
                local okf, sub = pcall(function() return v._type end)
                if okf and sub then
                    dump(prefix .. k .. '.', v, sub, depth + 1)
                else
                    -- bitfields: enumerate the true bits
                    local bits, any = {}, false
                    local okb = pcall(function()
                        for bk, bv in pairs(v) do
                            any = true
                            if bv == true then bits[#bits + 1] = bk end
                        end
                    end)
                    if okb and any then
                        table.sort(bits)
                        p(prefix .. k, '{' .. table.concat(bits, ',') .. '}')
                    end
                end
            end
        end
    end
end

dump('plotinfo.', df.global.plotinfo, df.plotinfost)

local ent = df.global.plotinfo.main.fortress_entity
if ent then
    p('entity.id', ent.id)
    p('entity.type', df.historical_entity_type[ent.type])
    for _, k in ipairs {'positions', 'resources', 'histfig_ids', 'nemesis_ids',
                        'members', 'guild_professions', 'occasion_info'} do
        local ok, v = pcall(function() return #ent[k] end)
        p('entity.' .. k .. '.n', ok and v or 'ERR')
    end
    local ok = pcall(function()
        p('entity.positions.own.n', #ent.positions.own)
        p('entity.positions.assignments.n', #ent.positions.assignments)
    end)
    p('entity.pos_dump_ok', ok)
end

p('gametype', df.game_type[df.global.gametype])
p('cur_year', df.global.cur_year)

table.sort(out)
local port = os.getenv('DFHACK_PORT') or 'x'
local f = assert(io.open('/tmp/plotdump.' .. port .. '.txt', 'w'))
f:write(table.concat(out, '\n'), '\n')
f:close()
print('wrote /tmp/plotdump.' .. port .. '.txt lines=' .. #out)
