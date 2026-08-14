-- Decode the real work orders on a hand-played fort. This is the mechanic to copy:
-- a work order in DF is not "make N of X" — it is "make N of X, out of this material,
-- WHILE these stock conditions hold, re-checked on this schedule", and the manager is
-- what turns that into jobs.
--
-- Run it against a save a human has actually played, then build to what it prints.

local w = df.global.world
local CMP = df.logic_condition_type
local FREQ = df.workquota_frequency_type

local function matname(mat_type, mat_index)
    if mat_type < 0 then return 'any' end
    local mi = dfhack.matinfo.decode(mat_type, mat_index)
    return mi and mi:getToken() or (mat_type .. ':' .. mat_index)
end

local function flagnames(cond)
    local out = {}
    for _, fname in ipairs({ 'flags1', 'flags2', 'flags3', 'flags4', 'flags5' }) do
        pcall(function()
            for k, v in pairs(cond[fname]) do
                if v == true then out[#out + 1] = k end
            end
        end)
    end
    table.sort(out)
    return out
end

local with_cond, total = 0, #w.manager_orders.all
local limit = tonumber((...)) or 10

for _, o in ipairs(w.manager_orders.all) do
    if #o.item_conditions > 0 then
        with_cond = with_cond + 1
        if with_cond <= limit then
            print(string.format('#%d %s  x%d/%d  freq=%s  val=%s act=%s  next_check=%s/%s',
                o.id, df.job_type[o.job_type], o.amount_left, o.amount_total,
                tostring(FREQ[o.frequency]),
                tostring(o.status.validated), tostring(o.status.active),
                tostring(o.finished_year), tostring(o.finished_year_tick)))

            local mc = {}
            for k, v in pairs(o.material_category) do
                if v == true then mc[#mc + 1] = k end
            end
            if #mc > 0 then print('     material_category: ' .. table.concat(mc, ',')) end
            if o.item_type >= 0 then
                print(string.format('     makes: %s mat=%s',
                    tostring(df.item_type[o.item_type]), matname(o.mat_type, o.mat_index)))
            end

            for _, c in ipairs(o.item_conditions) do
                local it = c.item_type >= 0 and tostring(df.item_type[c.item_type]) or 'any'
                local fl = flagnames(c)
                print(string.format('     WHILE %s %d of %s (%s)%s',
                    tostring(CMP[c.compare_type]), c.compare_val, it,
                    matname(c.mat_type, c.mat_index),
                    #fl > 0 and ('  flags=' .. table.concat(fl, ',')) or ''))
            end
            for _, oc in ipairs(o.order_conditions) do
                print(string.format('     AFTER order #%s is %s',
                    tostring(oc.order_id), tostring(oc.condition)))
            end
        end
    end
end

print(string.format('-- %d of %d orders carry conditions', with_cond, total))

-- frequency spread across the whole list, conditions or not
local by_freq = {}
for _, o in ipairs(w.manager_orders.all) do
    local k = tostring(FREQ[o.frequency])
    by_freq[k] = (by_freq[k] or 0) + 1
end
local parts = {}
for k, v in pairs(by_freq) do parts[#parts + 1] = k .. '=' .. v end
table.sort(parts)
print('-- frequency: ' .. table.concat(parts, ' '))
