-- Minimal public test for the "30‑day CPU baseline" objective
-- This test validates that the rules‑based player can run a 30‑day simulation
-- without crashing, recording worst‑run metrics.

local test = require('test')
local runner = test.runner()

-- Load the player implementation under test
local player = require('player')

-- Helper to run the simulation for a given seed and capture metrics
local function run_seed(seed)
    local sim = player.new(seed)
    sim:run(30 * 24 * 60) -- run for 30 days in minutes
    return {
        seed = seed,
        cpu_time = sim.cpu_time(),
        worst_metric = sim.worst_metric(),
    }
end

-- Verify that the simulation completes successfully for several seeds
local function test_cpu_baseline()
    local results = {}
    for _, seed in ipairs({12345, 67890, 13579}) do
        local r = run_seed(seed)
        table.insert(results, r)
    end

    -- Ensure no simulation crashed (nil should not be present)
    assert(runner:check(#results == 3, 'Expected 3 successful runs'))
end

runner:add(test_cpu_baseline)
runner:run()
