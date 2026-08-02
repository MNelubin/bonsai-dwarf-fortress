-- bonsai-apply-actions: deterministic evaluator-side dispatch of the agent's action
-- intents (anti-forgery). Reads agent_actions.txt (tab-separated: verb\targ1\targ2),
-- applies ONLY the allow-listed verbs, never executes agent code. Reports counts.
-- Kept in sync with game_scorer.ALLOWED_VERBS.
-- the actions file is named per episode; parallel forts must not read each
-- other's intents
local path = (...) or "/srv/df-bonsai/current/agent_actions.txt"
local f = io.open(path, "r")
if not f then print("APPLY no-actions"); return end
local w = df.global.world
local cits = dfhack.units.getCitizens(true)
local u1 = cits[1]
local c = { set_labor = 0, designate_dig = 0, create_stockpile = 0, add_workorder = 0,
            build_workshop = 0, advance = 0 }

local function split(line)
    local t = {}
    for tok in string.gmatch(line, "[^\t]+") do t[#t + 1] = tok end
    return t
end

-- Placement cursor, persisted in a Lua global for the whole episode (globals survive
-- between dfhack-run calls). Without it every create_stockpile call recomputed the same
-- spots relative to the first citizen, so only the FIRST round ever placed anything and
-- the development term could be earned exactly once per episode.
_G.BONSAI_PLACE = _G.BONSAI_PLACE or { stock = 0, shop = 0, dig = nil }
local P = _G.BONSAI_PLACE

-- A ring of candidate build sites around the wagon, walked outwards. Keeps successive
-- placements on fresh ground instead of colliding with what is already there.
local function site(n, radius)
    if not u1 then return nil end
    local ring = radius + math.floor(n / 8) * 3
    local a = (n % 8) * (math.pi / 4)
    return math.floor(u1.pos.x + ring * math.cos(a)),
           math.floor(u1.pos.y + ring * math.sin(a)),
           u1.pos.z
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
        -- Digging in DF needs REACHABILITY. The old dispatch stamped dig flags on a
        -- 5x5x13 block straight down from a dwarf standing on the surface: the top layer
        -- is open air (a dig flag there is a no-op) and everything below is sealed rock
        -- nobody can walk to, so a live 10-fort-day episode excavated exactly zero tiles
        -- however many tiles were "designated".
        --
        -- So designate what a player would: a staircase down from the dwarf, then a room
        -- carved off each landing. Every tile is connected to the one above it.
        pcall(function()
            local n = tonumber(a[2]) or 25
            if not u1 then return end
            -- Pin the shaft head for the whole episode. Citizen[1] WANDERS, so using
            -- its live position started a fresh one-tile shaft at a new spot on every
            -- call (observed: 96,91 then 95,98) - orphaned designations that connect
            -- to nothing and can never be reached, hence zero tiles actually dug.
            P.dig = P.dig or { u1.pos.x, u1.pos.y, u1.pos.z }
            local ox, oy, oz = P.dig[1], P.dig[2], P.dig[3]
            local placed = 0
            local DIG = df.tile_dig_designation
            local function mark(x, y, z, kind)
                if placed >= n then return end
                pcall(function()
                    local des = dfhack.maps.getTileFlags(x, y, z)
                    if not des then return end
                    local tt = dfhack.maps.getTileType(x, y, z)
                    local sh = tt and df.tiletype.attrs[tt].shape
                    -- only solid rock is diggable; flagging air or an existing floor
                    -- silently achieves nothing
                    if kind == DIG.Default and sh ~= df.tiletype_shape.WALL then return end
                    des.dig = kind
                    -- Setting the tile flag is NOT enough. DF only rescans blocks that
                    -- are flagged as carrying new designations, so writing designations
                    -- through DFHack without this produced a perfectly valid staircase
                    -- that generated ZERO dig jobs: measured 11 tiles marked, 0 jobs,
                    -- 0 rock removed over 3000 ticks, while `dig-now` on the same
                    -- designations excavated 35 tiles immediately.
                    local blk = dfhack.maps.getTileBlock(x, y, z)
                    if blk then blk.flags.designated = true end
                    placed = placed + 1
                end)
            end
            -- shaft: down-stair at the surface, up/down stairs beneath it
            mark(ox, oy, oz, DIG.DownStair)
            local depth = 0
            for dz = 1, 10 do
                mark(ox, oy, oz - dz, DIG.UpDownStair)
                depth = dz
                if placed >= n then break end
            end
            -- rooms off each landing, spiralling out so successive calls extend the fort
            -- rather than re-designating the same tiles
            P.digring = (P.digring or 0)
            for dz = 1, depth do
                for r = 1 + P.digring, 3 + P.digring do
                    for _, d in ipairs({ { r, 0 }, { -r, 0 }, { 0, r }, { 0, -r } }) do
                        mark(ox + d[1], oy + d[2], oz - dz, DIG.Default)
                        if placed >= n then break end
                    end
                    if placed >= n then break end
                end
                if placed >= n then break end
            end
            if placed > 0 then
                P.digring = P.digring + 1
                -- ask the engine to run its dig-job scan on the next tick
                pcall(function() df.global.process_dig = true end)
                pcall(function() df.global.process_jobs = true end)
            end
            c.designate_dig = c.designate_dig + placed
        end)
    elseif verb == "create_stockpile" then
        pcall(function()
            local n = tonumber(a[2]) or 1
            for _ = 1, n do
                local x, y, z = site(P.stock, 4)
                if x then
                    local ok = pcall(function()
                        local b = dfhack.buildings.constructBuilding{
                            type = df.building_type.Stockpile, abstract = true,
                            pos = { x = x, y = y, z = z }, width = 2, height = 2 }
                        if b then c.create_stockpile = c.create_stockpile + 1 end
                    end)
                    P.stock = P.stock + 1
                    if not ok then break end
                end
            end
        end)
    elseif verb == "build_workshop" then
        -- Without a workshop no manager order can ever be worked, so `workorders_done`
        -- was structurally pinned at 0 and half the development weight was unearnable.
        pcall(function()
            local name = a[2] or "Carpenters"
            local sub = df.workshop_type[name]
            if sub == nil then sub = df.workshop_type.Carpenters end
            local x, y, z = site(P.shop, 8)
            if x then
                local b = dfhack.buildings.constructBuilding{
                    type = df.building_type.Workshop, subtype = sub,
                    pos = { x = x, y = y, z = z } }
                if b then c.build_workshop = c.build_workshop + 1 end
                P.shop = P.shop + 1
            end
        end)
    elseif verb == "add_workorder" then
        pcall(function()
            local amount = tonumber(a[3]) or tonumber(a[2]) or 10
            -- The old dispatch used job_type.CustomReaction with no reaction attached:
            -- such an order can never be matched to work, so amount_left never fell and
            -- the observable stayed 0 no matter what the agent did. Name a real job.
            local jname = (a[2] and df.job_type[a[2]] ~= nil) and a[2] or "ConstructBed"
            local mo = df.manager_order:new()
            mo.job_type = df.job_type[jname]
            mo.amount_left = amount
            mo.amount_total = amount
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
