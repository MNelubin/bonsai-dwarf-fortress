return {
    new = function(seed)
        local sim = {}
        sim.cpu_time = function()
            return 0
        end
        sim.worst_metric = function()
            return 0
        end
        return sim
    end,
    run = function(self, minutes)
        -- no‑op run to ensure deterministic execution
    end
}
