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

-- Solid-tile count over the fort's bounding box. `dug_tiles` is the difference against
-- the T0 count, computed on the Python side: digging turns walls into floors, so a
-- falling solid count IS excavation. Before this the observable was never emitted at
-- all, so dug_tiles parsed as 0 forever and a third of the development term was blind
-- no matter how much the agent mined.
--
-- Costs ~30ms for a 25600-tile region read blockwise (measured live) — cheap enough to
-- sample every round, and the bbox keeps it off the full 192x192x66 map, which would
-- take ~1.9s.
local nsolid, nbbox = -1, 0
pcall(function()
  local m = w.map
  local xs, ys, zs = {}, {}, {}
  for _, u in ipairs(dfhack.units.getCitizens(true)) do
    xs[#xs+1] = u.pos.x; ys[#ys+1] = u.pos.y; zs[#zs+1] = u.pos.z
  end
  for _, b in ipairs(w.buildings.all) do
    xs[#xs+1] = b.x1; ys[#ys+1] = b.y1; zs[#zs+1] = b.z
    xs[#xs+1] = b.x2; ys[#ys+1] = b.y2; zs[#zs+1] = b.z
  end
  if #xs == 0 then return end
  local function span(t, pad, cap)
    local lo, hi = t[1], t[1]
    for _, v in ipairs(t) do if v < lo then lo = v end; if v > hi then hi = v end end
    return math.max(0, lo - pad), math.min(cap - 1, hi + pad)
  end
  -- PIN the region at T0 and never recompute it. A box derived from live citizen and
  -- building positions grows as the agent builds: measured live, nsolid jumped 33683
  -- -> 42084 within 2000 ticks purely because new stockpiles widened the box and
  -- dragged in 8401 tiles of untouched rock. That would have scored the agent on how
  -- far apart it scattered buildings, which is worse than the field being blind.
  local B = _G.BONSAI_SOLID_BOX
  if not B then
    local x0, x1 = span(xs, 20, m.x_count)
    local y0, y1 = span(ys, 20, m.y_count)
    local z0, z1 = span(zs, 8, m.z_count)
    B = { x0, y0, z0, x1, y1, z1 }
    _G.BONSAI_SOLID_BOX = B
  end
  local x0, y0, z0, x1, y1, z1 = B[1], B[2], B[3], B[4], B[5], B[6]
  local cnt = 0
  for z = z0, z1 do
    for bx = math.floor(x0 / 16), math.floor(x1 / 16) do
      for by = math.floor(y0 / 16), math.floor(y1 / 16) do
        local blk = dfhack.maps.getTileBlock(bx * 16, by * 16, z)
        if blk then
          local tt = blk.tiletype
          for iy = 0, 15 do for ix = 0, 15 do
            local sh = df.tiletype.attrs[tt[ix][iy]].shape
            if sh == df.tiletype_shape.WALL then cnt = cnt + 1 end
          end end
        end
        nbbox = nbbox + 256
      end
    end
  end
  nsolid = cnt
end)

print(string.format("OBS t=%d ncit=%d ndead=%d hsum=%d tsum=%d strsum=%d strdang=%d nfood=%d ndrink=%d nbuild=%d worders=%d nsolid=%d nbbox=%d nwild=%d nitems=%d nunits=%d cids=%s",
  tickabs, ncit, ndead, hsum, tsum, strsum, strdang, nfood, ndrink, nbuild, worders,
  nsolid, nbbox,
  (function() local n=0; pcall(function() for _,u in ipairs(w.units.active) do if dfhack.units.isWildlife(u) then n=n+1 end end end); return n end)(),
  #w.items.all, #w.units.all, table.concat(cids, ",")))
