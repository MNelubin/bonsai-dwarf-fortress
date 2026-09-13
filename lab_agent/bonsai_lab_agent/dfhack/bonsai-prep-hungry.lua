-- Scenario prep: the same embark, but the larder is gone and everyone is hungry.
--
-- Idling the fresh embark does NOT get here: the dwarves gather plants and drink from the
-- pond, so stocks never fall, and the first death at day 40 came with full stores. So
-- the state is set directly, before T0. Hunger lands between COMFORT_HUNGER_SATED
-- (40317) and UNMET (65723) and thirst between 20014 and 36076, so comfort reads well
-- under 1.0 at the start and provisioning near 0 -- and both can MOVE, which on the
-- untouched saves they never do. A policy that feeds the fort earns them back; one that
-- only digs watches them fall.
--
-- Run by DFSession.boot() when BONSAI_EPISODE_PREP=bonsai-prep-hungry. Saving the state
-- into a save file was tried first: DFHack's quicksave drives save() from a GUI overlay
-- that never renders headless, and requesting the autosave directly is accepted and
-- silently produces nothing. A prep script needs no save machinery at all.
local w = df.global.world
local HUNGER, THIRST = 52000, 28000
local edible = { [df.item_type.MEAT] = 1, [df.item_type.FISH] = 1, [df.item_type.PLANT] = 1,
                 [df.item_type.CHEESE] = 1, [df.item_type.EGG] = 1, [df.item_type.FISH_RAW] = 1 }
local food, drink, set = 0, 0, 0
for i = #w.items.all - 1, 0, -1 do
  local it = w.items.all[i]
  local ok, ty = pcall(function() return it:getType() end)
  if ok then
    -- items.remove() fails silently on anything held inside the wagon; the garbage flag
    -- lets DF delete it on the next tick, holder or not
    if ty == df.item_type.DRINK then it.flags.garbage_collect = true; it.flags.forbid = true; drink = drink + 1
    elseif edible[ty] then it.flags.garbage_collect = true; it.flags.forbid = true; food = food + 1 end
  end
end
for _, u in ipairs(w.units.active) do
  if dfhack.units.isCitizen(u) and not dfhack.units.isDead(u) then
    u.counters2.hunger_timer = HUNGER
    u.counters2.thirst_timer = THIRST
    set = set + 1
  end
end
print(string.format("PREP hungry: flagged food=%d drink=%d, %d citizens set to hunger=%d thirst=%d",
                    food, drink, set, HUNGER, THIRST))
