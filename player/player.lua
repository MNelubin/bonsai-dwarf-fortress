-- Minimal rules‑based player for the 30‑day CPU baseline test
local Player = {}

function Player.new(seed)
    -- In a real implementation this would load the rules and seed
    return setmetatable({seed=seed, minutes=0, cpu_time=0, worst_metric=0}, {__index=Player})
end

function Player:run(duration)
    -- Simple simulation: consume one CPU unit per minute
    self.minutes = duration
    self.cpu_time = duration  -- pretend each minute costs 1 unit of CPU
    -- worst_metric could be derived from simulation state; stub with 0
    self.worst_metric = 0
end

function Player:cpu_time()
    return self.cpu_time
end

function Player:worst_metric()
    return self.worst_metric
end

return Player
