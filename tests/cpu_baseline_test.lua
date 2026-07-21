-- tests/cpu_baseline_test.lua
-- Deterministic public test for bridge/cpu_baseline.lua
-- Ensures that the baseline runs for exactly 30 in‑game days and produces a JSON report.

local luajit = require('luaunit')
local Bridge = require('bridge')

-- Mock Game object to control day progression and capture events
local Game = {}
local day = 0
local job_counter = 0
local tick_counter = 0

function Game:on(event, fn)
    self.__handlers = self.__handlers or {}
    self.__handlers[event] = fn
end

function Game:emit(event, ...)
    local fn = self.__handlers[event]
    if fn then fn(...) end
end

function Game:on('day_start')
    day = day + 1
    -- trigger bridge tick on day start
    Bridge.tick()
    -- Run extra ticks to simulate a full day (deterministic count)
    for i=1, 120 do Bridge.tick() end
    -- Emit job events randomly to exercise counters without affecting logic
    if math.random() < 0.5 then
        job_counter = job_counter + 1
        self:emit('job_start', {id=job_counter})
    end
    self:emit('tick', i)
end

-- Load the module under test; side‑effects populate the Bridge singleton
local ok, _ = pcall(function() dofile('bridge/cpu_baseline.lua') end)
assert.ok(ok, 'module should load without error')

-- Simulate the passage of days until the module signals completion
while day < 30 do
    Bridge.tick() -- minimal tick to keep Bridge alive while day logic runs
end

-- Bridge should have signalled finish after 30 days
assert.IsTrue(Bridge.finished, 'Bridge should finish after 30 days')

-- Capture the final report printed to stdout
local report = Bridge.last_output
assertNotNil(report, 'report should be captured')
local parsed = luajit.json.decode(report)
assertIsTable(parsed, 'report must be JSON object')
assert(parsed.cycles > 0, 'cycle metric must be positive')
assert(parsed.jobs > 0, 'jobs metric must be positive')
assert(parsed.ticks > 0, 'ticks metric must be positive')

-- Ensure that the metrics are deterministic given the fixed simulation steps
assertEquals(parsed.cycles, 120*30 + 30, 'expected cycles count')
assertEquals(parsed.jobs, math.floor(30*0.5), 'expected jobs count')
assertEquals(parsed.ticks, 120*30 + 30, 'expected ticks count')
