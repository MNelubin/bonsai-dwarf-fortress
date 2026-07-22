return {
    description = "30‑day CPU baseline test",
    run = function(state)
        -- Ensure rules‑based player runs for 30 days across seeds
        local start = df.unit.time
        for seed = 1,10 do
            state:evaluate_game(seed)
            local end_time = df.unit.time
            if end_time - start < 30 * 14400 then -- 30 days in DF ticks
                error('Insufficient runtime for seed '..seed)
            end
        end
        return true
    end
}
