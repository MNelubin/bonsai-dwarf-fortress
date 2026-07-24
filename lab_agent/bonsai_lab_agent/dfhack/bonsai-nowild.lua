-- Stop wildlife influx: zero every world population's available quantity.
local w = df.global.world
local n = 0
for _, p in ipairs(w.populations.all) do
  pcall(function() p.quantity = 0; p.quantity_max = 0; n = n + 1 end)
end
-- also vanish the units currently on the map that are wild (clean, and one-shot at T0)
local culled = 0
pcall(function()
  for _, u in ipairs(w.units.active) do
    pcall(function()
      if not dfhack.units.isCitizen(u) and dfhack.units.isWildlife(u) then
        u.flags1.forest = false
        u.animal.vanish_countdown = 1
        culled = culled + 1
      end
    end)
  end
end)
print(string.format("nowild: zeroed=%d culled_T0=%d", n, culled))
