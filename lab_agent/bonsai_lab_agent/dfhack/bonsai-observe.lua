-- Ground-truth observable vector for the trusted evaluator. Emits stable dwarf/fort
-- signals only; wildlife/item-total excluded from scoring (noisy). See metric.py.
local w = df.global.world
local tickabs = df.global.cur_year * 1000000 + df.global.cur_year_tick
local STRESS_DANGER = 100000
local cids, hsum, tsum, ncit, strsum, strdang = {}, 0, 0, 0, 0, 0
pcall(function()
  for _, u in ipairs(dfhack.units.getCitizens(true)) do
    ncit = ncit + 1; cids[#cids+1] = u.id
    pcall(function() hsum = hsum + (u.counters2.hunger_timer or 0) end)
    pcall(function() tsum = tsum + (u.counters2.thirst_timer or 0) end)
    pcall(function()
      local s = u.status.current_soul.personality.stress or 0
      strsum = strsum + s
      if s > STRESS_DANGER then strdang = strdang + 1 end
    end)
  end
end)
local ndrink, nfood = 0, 0
pcall(function()
  for _, it in ipairs(w.items.all) do
    local ok, ty = pcall(function() return it:getType() end)
    if ok then
      if ty == df.item_type.DRINK then ndrink = ndrink + 1
      elseif ty == df.item_type.MEAT or ty == df.item_type.FISH or ty == df.item_type.PLANT
          or ty == df.item_type.CHEESE or ty == df.item_type.EGG or ty == df.item_type.FISH_RAW then nfood = nfood + 1 end
    end
  end
end)
local nbuild, ndead, worders = 0, 0, 0
pcall(function() nbuild = #w.buildings.all end)
pcall(function() for _,u in ipairs(w.units.all) do if dfhack.units.isDead(u) then ndead = ndead + 1 end end end)
-- completed manager-order units (development proxy that is NOT wildlife-contaminated)
pcall(function()
  for _, o in ipairs(w.manager_orders.all) do
    pcall(function() worders = worders + math.max(0, (o.amount_total or 0) - (o.amount_left or 0)) end)
  end
end)
print(string.format("OBS t=%d ncit=%d ndead=%d hsum=%d tsum=%d strsum=%d strdang=%d nfood=%d ndrink=%d nbuild=%d worders=%d nwild=%d nitems=%d nunits=%d cids=%s",
  tickabs, ncit, ndead, hsum, tsum, strsum, strdang, nfood, ndrink, nbuild, worders,
  (function() local n=0; pcall(function() for _,u in ipairs(w.units.active) do if dfhack.units.isWildlife(u) then n=n+1 end end end); return n end)(),
  #w.items.all, #w.units.all, table.concat(cids, ",")))
