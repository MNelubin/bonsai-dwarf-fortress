-- bonsai-apply-actions: deterministic evaluator-side dispatch of the agent's action
-- intents (anti-forgery). Reads agent_actions.txt (tab-separated: verb\targ1\targ2),
-- applies ONLY the allow-listed verbs, never executes agent code. Reports counts.
-- Kept in sync with game_scorer.ALLOWED_VERBS.
local path = "/srv/df-bonsai/current/agent_actions.txt"
local f = io.open(path, "r")
if not f then print("APPLY no-actions"); return end
local w = df.global.world
local cits = dfhack.units.getCitizens(true)
local u1 = cits[1]
local c = {set_labor = 0, designate_dig = 0, create_stockpile = 0, add_workorder = 0, advance = 0}

local function split(line)
    local t = {}
    for tok in string.gmatch(line, "[^\t]+") do t[#t + 1] = tok end
    return t
end

for line in f:lines() do
    local a = split(line)
    local verb = a[1]
    if verb == "set_labor" then
        pcall(function()
            local lid = df.unit_labor[a[2]]
            if lid then
                local on = (a[3] ~= "False" and a[3] ~= "false" and a[3] ~= "0")
                for _, u in ipairs(cits) do u.status.labors[lid] = on end
                c.set_labor = c.set_labor + 1
            end
        end)
    elseif verb == "designate_dig" then
        pcall(function()
            local n = tonumber(a[2]) or 25
            if u1 then
                local dug = 0
                for dz = 0, 12 do for dx = -2, 2 do for dy = -2, 2 do
                    if dug < n then pcall(function()
                        local des = dfhack.maps.getTileFlags(u1.pos.x + dx, u1.pos.y + dy, u1.pos.z - dz)
                        if des then des.dig = df.tile_dig_designation.Default; dug = dug + 1 end
                    end) end
                end end end
                c.designate_dig = c.designate_dig + dug
            end
        end)
    elseif verb == "create_stockpile" then
        pcall(function()
            local n = tonumber(a[2]) or 1
            if u1 then for i = 0, n - 1 do pcall(function()
                local b = dfhack.buildings.constructBuilding{type = df.building_type.Stockpile,
                    abstract = true, pos = {x = u1.pos.x + 3 + i * 3, y = u1.pos.y, z = u1.pos.z},
                    width = 2, height = 2}
                if b then c.create_stockpile = c.create_stockpile + 1 end
            end) end end
        end)
    elseif verb == "add_workorder" then
        pcall(function()
            local amount = tonumber(a[2]) or 10
            local mo = df.manager_order:new()
            mo.job_type = df.job_type.CustomReaction
            mo.amount_left = amount; mo.amount_total = amount
            w.manager_orders.all:insert("#", mo)
            c.add_workorder = c.add_workorder + 1
        end)
    end
end
f:close()
local rep = {}
for k, v in pairs(c) do rep[#rep + 1] = k .. "=" .. v end
table.sort(rep)
print("APPLY " .. table.concat(rep, " "))
