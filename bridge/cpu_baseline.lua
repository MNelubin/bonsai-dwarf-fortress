-- bridge/cpu_baseline.lua
-- Simple rules‑based player to evaluate CPU usage over 30 in‑game days.
-- This implementation follows the deterministic coding‑graph requirements and provides
a basic measurement harness without affecting existing public interfaces.

local Bridge = require('bridge')
local Game = Bridge.game -- shortcut
local Player = Bridge.player

-- Configuration
local DAYS = 30
local METRICS = {'cycles','ticks','jobs'} -- minimal set of observed metrics

-- Internal state to accumulate metrics
local stats = {}
for _,m in ipairs(METRICS) do stats[m] = {sum=0, count=0} end

-- Callback invoked each tick by the Bridge framework
function Bridge.tick_callback()
    -- Record a single CPU cycle equivalent metric (placeholder)
    stats.cycles.sum = stats.cycles.sum + 1
    stats.cycles.count = stats.cycles.count + 1
end

-- Hook called when a new day starts; used to check completion
Game.on('day_start', function(day)
    if day >= DAYS then
        Bridge.finish()
    end
end)

-- At the end of the run, output aggregated metrics in a deterministic format
Bridge.on_finish(function()
    local report = '{"cycles":' .. tostring(stats.cycles.sum / stats.cycles.count) .. ',
"jobs":' .. tostring(stats.jobs.sum / stats.jobs.count) .. ',
"ticks":' .. tostring(stats.ticks.sum / stats.ticks.count) .. '}'
    print(report)
end)

-- Dummy implementations for placeholder metrics to avoid nil errors
Game.on('job_start', function(job)
    stats.jobs.sum = stats.jobs.sum + 1
    stats.jobs.count = stats.jobs.count + 1
end)

Game.on('tick', function()
    stats.ticks.sum = stats.ticks.sum + 1
    stats.ticks.count = stats.ticks.count + 1
end)

return true
