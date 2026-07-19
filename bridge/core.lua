-- DFHack Bridge: core state observation, action dispatch, and game control.
-- Designed for headless deterministic episodes on DF 53.15 / DFHack 53.15-r2.
--@ module = true

local bridge = {}

--- Ticks per season constant (verified from position.lua).
bridge.TICKS_PER_DAY = 86400
bridge.TICKS_PER_SEASON = 3600 * bridge.TICKS_PER_DAY

--- Current timestamp as a single table.
function bridge.observe()
    if not df.global then
        return { error = "DF not initialized" }
    end

    local gametype = nil
    if df.global.gametype then
        gametype = tostring(df.global.gametype)
    end

    local units = {}
    if dfhack.units.getUnits then
        for _, u in ipairs(dfhack.units.getUnits()) do
            local pos = {0, 0, 0}
            if u.pos then
                pos = {u.pos.x, u.pos.y, u.pos.z}
            end
            table.insert(units, {
                id       = u.id,
                race     = dfhack.units.getRace(u),
                civ_id   = u.civ_id,
                killed   = u.flags2.killed,
                pos      = pos,
            })
        end
    end

    -- Delegated to bridge.building_list() below.
    local buildings = bridge.building_list()

    return {
        version    = "1.0",
        gametype   = gametype,
        cur_year   = df.global.cur_year or nil,
        cur_season = df.global.cur_season or nil,
        cur_tick   = df.global.cur_year_tick or nil,
        paused     = df.global.pause_state,
        units      = units,
        buildings  = buildings,
        tick       = bridge.tickcount(),
    }
end

--- Internal monotonic tick counter for the bridge.
local _tickcount = 0
function bridge.tickcount()
    return _tickcount
end

--- Reset internal bridge state between episodes.
function bridge.reset()
    _tickcount = 0
    bridge._hooks_registered = false
    if bridge._obs_callback then
        dfhack.onStateChange.BonsaiObserve = nil
        bridge._obs_callback = nil
    end
end

--- Register the observe callback on DF's state change.
function bridge.start_observing(callback)
    if bridge._hooks_registered then return end
    bridge._obs_callback = callback
    dfhack.onStateChange.BonsaiObserve = function(event)
        local obs = bridge.observe()
        if callback and callback.__name == "json_callback" then
            local json = require("data-JSON")
            callback(json.write(obs))
        else
            callback(obs)
        end
    end
    bridge._hooks_registered = true
end

--- Dispatch a single action to the game. Returns {ok, message}.
function bridge.act(action)
    if not df.global then
        return { ok = false, message = "DF not initialized" }
    end

    local name = action.command or action.name
    if not name then
        return { ok = false, message = "no command specified" }
    end

    local args = {}
    if type(action.args) == "table" then
        for k, v in pairs(action.args) do
            table.insert(args, tostring(v))
        end
    elseif action.args and type(action.args) == "string" then
        table.insert(args, action.args)
    end

    local args_str = table.concat(args, " ")
    _tickcount = _tickcount + 1

    if name == "pause" then
        df.global.pause_state = true
        return { ok = true, message = "paused" }
    elseif name == "unpause" then
        df.global.pause_state = false
        return { ok = true, message = "unpaused" }
    elseif name == "observe" then
        return { ok = true, message = bridge.observe() }
    else
        local code, output = dfhack.run_command(name .. " " .. args_str)
        return { ok = (code == 0), message = tostring(code), output = output }
    end
end

--- Advance the game by N ticks. Returns {ok, advanced_ticks}.
function bridge.advance(ticks)
    if not df.global then
        return { ok = false, message = "DF not initialized" }
    end

    local target_start = df.global.cur_year_tick or 0
    df.global.pause_state = false
    _tickcount = _tickcount + 1

    local function poll()
        local now = df.global.cur_year_tick or 0
        if (now - target_start) >= ticks then
            return true
        end
    end

    local deadline = os.clock() + 60
    while os.clock() < deadline do
        if poll() then return { ok = true, advanced_ticks = ticks } end
        dfhack.timeout(1, "ticks", function() end)
    end

    return { ok = false, message = "advance timeout" }
end

--- Tile / map grid mechanic observation.
-- Verified APIs (from hack/lua/dfhack.lua, tile-material.lua, plugin source):
--   dfhack.maps.getTileSize()    -> x, y, z tile counts (returns df.global.world.map.*_count)
--   dfhack.maps.getSize()        -> block counts
--   dfhack.maps.isValidTilePos(x,y,z) -> boolean
--   dfhack.maps.getTileType({x=x,y=y,z=z}) -> integer tile type or nil
--   df.tiletype.attrs[typ].material  -> tiletype_material enum (SOIL, STONE, etc.)
--   df.tiletype.iswalkable(typ)      -> boolean walkability flag
-- Returns a compact snapshot of map dimensions and sampled tiles at z=0.
function bridge.tile_map()
    local result = {
        has_map = false,
        width  = 0,
        height = 0,
        depth  = 0,
        block_width  = 0,
        block_height = 0,
        block_depth  = 0,
        tiles = {},
    }

    if not df.global or not df.global.world then
        return result
    end

    -- Guard: do nothing when the map is nil (pre-game or no active world).
    local map = df.global.world.map
    if not map then
        return result
    end

    result.has_map = true

    -- Map dimensions in tile units.
    result.width  = map.x_count or 0
    result.height = map.y_count or 0
    result.depth  = map.z_count or 0

    -- Map dimensions in block units (each block = 16x16x16 tiles).
    result.block_width  = map.x_count_block or 0
    result.block_height = map.y_count_block or 0
    result.block_depth  = map.z_count_block or 0

    -- Sample a bounded set of tiles along the bottom z-layer (z=0) for compact output.
    if dfhack.maps then
        local limit = math.min(result.width * result.height, 256)
        local sampled = 0
        for zx = 0, result.width - 1 do
            if sampled >= limit then break end
            for zy = 0, result.height - 1 do
                if sampled >= limit then break end

                local pos = {x = zx, y = zy, z = 0}
                if not dfhack.maps.isValidTilePos(pos) then
                    goto continue_loop
                end

                local tt = dfhack.maps.getTileType(pos)
                if tt and type(tt) == "number" then
                    -- Classify material class.
                    local mat = "unknown"
                    pcall(function()
                        local attr_mt = df.tiletype.attrs[tt].material
                        -- Walk the tiletype_material enum to get a human label.
                        for k, v in pairs(df.tiletype_material) do
                            if type(v) == "number" and v  == attr_mt then
                                mat = k
                                break
                            end
                        end
                    end)

                    local walkable = false
                    pcall(function()
                        walkable = df.tiletype.iswalkable(tt) or false
                    end)

                    table.insert(result.tiles, {
                        x        = zx,
                        y        = zy,
                        z        = 0,
                        type     = tt,
                        material = mat,
                        walkable = walkable,
                    })
                    sampled = sampled + 1
                end

                ::continue_loop::
            end
        end
    end

    return result
end

--- Unit needs / counters mechanic observation.
-- Verified APIs (from hack/scripts/internal/gm-unit/editor_counters.lua and
-- hack/scripts/internal/notify/notifications.lua in DFHack 53.15-r2):
--   unit.counters:    job_counter, swap_counter, winded, stunned, unconscious,
--                     suffocation, webbed, soldier_mood_countdown, soldier_mood,
--                     pain, nausea, dizziness
--   unit.counters2:   paralysis, numbness, fever, exhaustion, hunger_timer,
--                     thirst_timer, sleepiness_timer, stomach_content,
--                     stomach_food, vomit_timeout, stored_fat
--   is_in_dire_need thresholds: hunger > 75000, thirst > 50000,
--                              sleepiness > 150000
-- Returns a snapshot of counters for every living unit.
function bridge.unit_needs()
    local result = {}
    if not df.global or not df.global.world then
        return result
    end
    if not dfhack.units then
        return result
    end

    for _, u in ipairs(dfhack.units.getUnits()) do
        if dfhack.units.isDead(u) and not u.flags1.inactive then
            goto continue_needs
        end

        local needs = {
            id  = u.id,
        }

        -- Counters group 1 (physical state counters).
        if u.counters then
            pcall(function()
                needs.job_counter    = u.counters.job_counter or 0
                needs.swap_counter   = u.counters.swap_counter or 0
                needs.winded         = u.counters.winded or 0
                needs.stunned        = u.counters.stunned or 0
                needs.unconscious    = u.counters.unconscious or 0
                needs.suffocation    = u.counters.suffocation or 0
                needs.webbed         = u.counters.webbed or 0
                needs.pain           = u.counters.pain or 0
                needs.nausea         = u.counters.nausea or 0
                needs.dizziness      = u.counters.dizziness or 0
            end)
        end

        -- Counters group 2 (needs / vitality counters).
        if u.counters2 then
            pcall(function()
                needs.hunger_timer     = u.counters2.hunger_timer or 0
                needs.thirst_timer     = u.counters2.thirst_timer or 0
                needs.sleepiness_timer = u.counters2.sleepiness_timer or 0
                needs.exhaustion       = u.counters2.exhaustion or 0
                needs.stomach_content  = u.counters2.stomach_content or 0
                needs.stored_fat       = u.counters2.stored_fat or 0
            end)
        end

        table.insert(result, needs)

        ::continue_needs::
    end

    return result
end

--- Job system observation — DF 53.15 verified via suspendmanager.lua, dwarfvet.lua, stockflow.lua.
-- Job accessors verified:
--   df.global.world.jobs.list          → vector of all job records
--   job.job_type                       → df.job_type enum (ConstructBed, SmeltOre, …)
--   job.flags.suspend                  → true if job is suspended
--   job.flags.cancelled                → true if job was cancelled
--   dfhack.job.getWorker(job)          → unit working on the job or nil
--   dfhack.job.getName(job)           → human-readable caption string
--   job.pos                            → {x, y, z} tile position of the job
function bridge.job_list()
    local result = {}
    if not df.global or not df.global.world then
        return result
    end

    -- Guard: jobs vector may not exist before a map load.
    if not df.global.world.jobs then
        return result
    end
    if not df.global.world.jobs.list then
        return result
    end

    for _, job in ipairs(df.global.world.jobs.list) do
        local jtype = "unknown"
        pcall(function()
            jtype = tostring(df.job_type[job.job_type]) or "unknown"
        end)

        local suspended, cancelled, finished = false, false, false
        if job.flags then
            pcall(function()
                suspended = job.flags.suspend or false
                cancelled = job.flags.cancelled or false
            end)
        end

        -- Finished jobs are not typically in the active list, but flag for completeness.
        if finished or (cancelled == false and suspended == false) then
            -- Heuristic: non-cancelled non-suspended → active/queued
        end

        local worker_id = nil
        local worker_name = nil
        pcall(function()
            local wkr = dfhack.job.getWorker(job)
            if wkr then
                worker_id = wkr.id
            end
        end)

        local job_pos = {x = 0, y = 0, z = 0}
        if job.pos then
            job_pos = {x = job.pos.x or 0, y = job.pos.y or 0, z = job.pos.z or 0}
        end

        -- Count input items (materials required).
        local n_items = 0
        pcall(function()
            if job.job_items and job.job_items.elements then
                n_items = #job.job_items.elements
            end
        end)

        local job_name = nil
        pcall(function()
            job_name = dfhack.job.getName(job) or nil
        end)

        table.insert(result, {
            id         = job.id or nil,
            type       = jtype,
            cancelled  = cancelled,
            suspended  = suspended,
            pos        = job_pos,
            worker_id  = worker_id,
            n_items    = n_items,
            name       = job_name,
        })
    end

    return result
end

--- Building list observation.
-- Verified fields from DFHack scripts (extra-gamelog.lua, siegemanager.lua, advfort.lua):
--   building.id                      — unique numeric identifier
--   building.type                    — df.building_type enum integer
--   building.subtype                 — subtype enum (workshop_kind, furnace_type, etc.)
--   building.custom_type             — custom blueprint ID or -1
--   building.centerx / centery / centerz  — center tile coordinates
--   building.flags.exists            — true when construction finished
--   dfhack.buildings.isComplete(bld) — boolean: fully built?
--   bld:getType(), :getSubtype()     — accessor methods
--   bld:getBuildStage(), :getMaxBuildStage() — integer build progress 0..N
function bridge.building_list()
    local buildings = {}
    if not df.global.world or not df.global.world.buildings then
        return buildings
    end

    local all_buildings = df.global.world.buildings.all or {}
    local count = #all_buildings
    for i = 1, math.min(count, 200) do
        local bld = all_buildings[i - 1]
        if not bld then goto continue end

        local btype = "unknown"
        local subtype = nil
        pcall(function()
            btype = tostring(df.building_type[bld:getType()]) or "unknown"
        end)
        pcall(function()
            subtype = bld:getSubtype()
        end)

        local cx, cy, cz = 0, 0, 0
        if bld.centerx then
            cx = bld.centerx or 0
            cy = bld.centery or 0
            cz = bld.centerz or 0
        end

        local built = false
        if bld.flags then
            pcall(function()
                built = bld.flags.exists or false
            end)
        end

        local build_stage = -1
        local max_stage = -1
        pcall(function()
            build_stage = bld:getBuildStage()
        end)
        pcall(function()
            max_stage = bld:getMaxBuildStage()
        end)

        local custom_id = -1
        pcall(function()
            custom_id = bld.custom_type or -1
        end)

        table.insert(buildings, {
            idx         = i,
            id          = bld.id or nil,
            type        = btype,
            subtype     = subtype,
            custom_id   = custom_id,
            center      = {x = cx, y = cy, z = cz},
            built       = built,
            build_stage = build_stage,
            max_stage   = max_stage,
        })

        ::continue::
    end

    return buildings
end

return bridge
