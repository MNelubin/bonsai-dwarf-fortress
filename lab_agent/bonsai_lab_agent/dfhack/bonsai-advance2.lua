-- Robust tick advance: clears blocking popups EVERY GRAPHIC FRAME (fires even
-- when the sim is popup-frozen, unlike 'ticks' timeouts) and counts sim frames
-- via world.frame_counter. Advances exactly N sim ticks, then pauses.
-- Tick count comes in as a script argument, not a shared file. With several
-- episodes running at once on different ports they all live in the same DF
-- directory, so a single advance_n.txt is a race: one fort reads another's horizon.
local n = tonumber((...))
if not n then
  local f = io.open('/srv/df-bonsai/current/advance_n.txt','r')   -- legacy fallback
  if f then n = tonumber((f:read('*l'))); f:close() end
end
n = n or 100
local w = df.global.world
local start = w.frame_counter
local function heartbeat()
  pcall(function() w.status.popups:resize(0) end)          -- unblock modal popups
  pcall(function() df.global.world.status.flags.DID_ANNOUNCE = false end)
  if w.frame_counter - start >= n then
    df.global.pause_state = true
    return                                                  -- stop: target reached
  end
  df.global.pause_state = false
  dfhack.timeout(1, 'frames', heartbeat)                    -- reschedule next graphic frame
end
heartbeat()
print(string.format('ADV2 start_frame=%d n=%d', start, n))
