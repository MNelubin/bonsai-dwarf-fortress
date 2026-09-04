-- bridge/contract.lua
-- Thin adapter over bridge.core for the public contract.

local core = require('bridge.core')
local M = {}

-- reset: delegate to core.reset, returning nil.
function M.reset()
    core.reset()
    return
end

-- observe: delegate to core.observe, returning the observation table.
function M.observe()
    return core.observe()
end

-- act: validate input is a table, then delegate to core.act.
function M.act(action)
    if type(action) ~= "table" then
        return { ok = false, message = "act requires a table" }
    end
    local command = action.command or action.name
    if not command then
        return { ok = false, message = "act requires a 'command' field" }
    end
    local args = action.args
    -- core.act expects fields name and args; forward unchanged.
    return core.act({ name = command, args = args })
end

-- advance: validate positive integer, then delegate to core.advance.
function M.advance(ticks)
    if type(ticks) ~= "number" or ticks < 1 then
        return { ok = false, message = "advance requires a positive integer" }
    end
    return core.advance(ticks)
end

return M
