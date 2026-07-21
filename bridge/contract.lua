-- bridge/contract.lua
-- Minimal deterministic Bridge contract implementation.

local M = {}

-- Reset the internal state.
function M.reset()
    return {status = "reset"}
end

-- Observe the current state. Deterministic placeholder.
function M.observe()
    return {
        status = "ok",
        timestamp = 0,
        state = "idle"
    }
end

-- Act based on a JSON action description.
function M.act(action)
    return {status = "ok", performed = action}
end

-- Advance the simulation.
function M.advance(step)
    return {status = "ok", advanced = step}
end

-- Register the API functions with the DFHack bridge.
local bridge = require "bridge"
bridge.register{
    reset = M.reset,
    observe = M.observe,
    act = M.act,
    advance = M.advance,
}

return M