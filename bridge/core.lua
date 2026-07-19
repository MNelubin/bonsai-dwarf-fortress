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

    local buildings = {}
    if df.global.world and df.global.world.buildings then
        local count = #df.global.world.buildings.all or 0
        for i = 1, math.min(count, 200) do
            table.insert(buildings, { idx = i })
        end
    end

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

return bridge
