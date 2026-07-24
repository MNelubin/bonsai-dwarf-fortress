-- Robust tick advance: clears blocking popups EVERY GRAPHIC FRAME (fires even
-- when the sim is popup-frozen, unlike 'ticks' timeouts) and counts sim frames
-- via world.frame_counter. Advances exactly N sim ticks, then pauses.
local n
local f = io.open('/srv/df-bonsai/current/advance_n.txt','r')
if f then n = tonumber((f:read('*l'))); f:close() end
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
