-- bonsai-headless-init: run on every fort load to keep the sim running unattended.
pcall(function() dfhack.run_command('enable', 'hide-tutorials') end)
pcall(function()
    for _, f in ipairs(df.global.d_init.announcements.flags) do
        f.PAUSE = false
        f.RECENTER = false
        f.DO_MEGA = false
    end
end)
pcall(function() df.global.world.status.popups:resize(0) end)
pcall(function() df.global.enabler.fps = 1000000 end)
-- Determinism: DF reseeds these RNGs from wall-clock on load; pin them to fixed seeds
-- so fortress simulation (wildlife spawns, events) is bit-reproducible across reloads.
pcall(function() df.global.game.play_rng.splitmix64_state = 880088008800088 end)
pcall(function() df.global.game.hash_rng.splitmix64_state = 990099009900099 end)
pcall(function() df.global.world.history_rng.splitmix64_state = 770077007700077 end)
print("bonsai-headless-init applied")
