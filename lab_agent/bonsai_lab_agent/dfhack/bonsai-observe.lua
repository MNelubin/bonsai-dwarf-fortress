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
-- Completed manager-order units. A development proxy that is not wildlife-contaminated,
-- but it has to be ACCUMULATED, not read off the live queue.
--
-- This used to sum (amount_total - amount_left) over CURRENTLY QUEUED orders. DF removes
-- an order from that list once it is done, so every completed order's contribution
-- vanished from the total: the counter was not monotonic and lost exactly the work that
-- succeeded. Measured on region3-lab at horizon 12000, the episode delta came out as -2,
-- and raw_components hid the decrease behind max(0, obs - t0). It also explains orders
-- reading 0 on the fresh embark after add_workorder had dispatched successfully - the
-- order completed and disappeared before the next observation.
--
-- DF keeps no completed-order history (manager_orders holds only `all` and
-- manager_order_next_id), so remember each order's delivered count by its own id and
-- keep the record after the order is gone. Delivered only ever grows for a given id, so
-- the sum is monotonic. The table lives as long as this DF process, which is exactly one
-- episode: bonsai_session.sh boots a fresh instance and T0 is taken after that.
_G.BONSAI_WORDERS_DELIVERED = _G.BONSAI_WORDERS_DELIVERED or {}
pcall(function()
  for _, o in ipairs(w.manager_orders.all) do
    pcall(function()
      local id = o.id
      local delivered = math.max(0, (o.amount_total or 0) - (o.amount_left or 0))
      local known = _G.BONSAI_WORDERS_DELIVERED[id] or 0
      if delivered > known then _G.BONSAI_WORDERS_DELIVERED[id] = delivered end
    end)
  end
  for _, delivered in pairs(_G.BONSAI_WORDERS_DELIVERED) do
    worders = worders + delivered
  end
end)

-- ---------------------------------------------------------------- action dependencies
-- Scored aggregates tell us whether the fort improved; they do not tell a controller
-- what prerequisite is missing. Count only claimable + reachable stock, mirroring the
-- dispatcher's bonsai-reach rule (including supplies held by the embark wagon).
local reach, reach_groups = nil, nil
pcall(function()
  reach = reqscript('bonsai-reach')
  reach_groups = reach.fort_groups()
end)

local stock = { WOOD=0, BOULDER=0, BLOCKS=0, BAR=0, BED=0, BARREL=0, SEEDS=0, PLANT=0 }
pcall(function()
  for _, it in ipairs(w.items.all) do
    local name = tostring(df.item_type[it:getType()])
    if stock[name] ~= nil and not it.flags.rotten then
      -- Containment nests: an embark seed is in a BAG and the BAG is in the wagon, so
      -- getHolderBuilding answers nil for it. Ask the chain, or the wagon exception
      -- below never fires and a fresh fort reports zero of everything it embarked with.
      local wagon = false
      if reach then
        pcall(function() wagon = reach.in_wagon(it) end)
      else
        pcall(function()
          local h = dfhack.items.getHolderBuilding(it)
          wagon = h ~= nil and h:getType() == df.building_type.Wagon
        end)
      end
      local usable = false
      if reach then
        usable = reach.item(it, reach_groups)
      else
        usable = not (it.flags.in_job or it.flags.forbid or it.flags.dump
                      or it.flags.construction or it.flags.removed
                      or (it.flags.foreign and not wagon))
      end
      -- An item already consumed by furniture/workshop construction is reachable but
      -- not stock. The embark wagon is the deliberate exception: its contents are the
      -- fort's starting supplies and the dispatcher can claim them directly.
      if usable and not wagon then
        local holder_bld = nil
        if reach then
          pcall(function() local _, b = reach.holder(it); holder_bld = b end)
        else
          pcall(function() holder_bld = dfhack.items.getHolderBuilding(it) end)
        end
        if holder_bld then usable = false end
      end
      if usable then stock[name] = stock[name] + 1 end
    end
  end
end)

local nworkshop, nbuiltshop, nunbuiltshop, nfarmplots = 0, 0, 0, 0
local shop_names = { 'Carpenters', 'Masons', 'Still', 'Craftsdwarfs', 'Farmers' }
local shops, pending_shops = {}, {}
for _, name in ipairs(shop_names) do shops[name], pending_shops[name] = 0, 0 end
pcall(function()
  for _, b in ipairs(w.buildings.all) do
    if b:getType() == df.building_type.FarmPlot then nfarmplots = nfarmplots + 1 end
    if df.building_workshopst:is_instance(b) then
      nworkshop = nworkshop + 1
      if b:getBuildStage() >= b:getMaxBuildStage() then
        nbuiltshop = nbuiltshop + 1
        local name = tostring(df.workshop_type[b.type])
        if shops[name] ~= nil then shops[name] = shops[name] + 1 end
      else
        nunbuiltshop = nunbuiltshop + 1
        local name = tostring(df.workshop_type[b.type])
        if pending_shops[name] ~= nil then pending_shops[name] = pending_shops[name] + 1 end
      end
    end
  end
end)

local njobs, nunassignedjobs, nmanagerjobs, nbrewjobs = 0, 0, 0, 0
pcall(function()
  local link = w.jobs.list.next
  while link do
    local job = link.item
    if job then
      njobs = njobs + 1
      -- df.job carries no worker_id field; the worker hangs off a general_ref and is
      -- read with dfhack.job.getWorker. Touching the absent field threw inside the
      -- pcall, so worker_id stayed -1 and EVERY job counted as unassigned —
      -- nunassignedjobs always came out equal to njobs. On the mature fort 73 of the
      -- 115 jobs actually have a worker.
      local worker, by_manager = nil, false
      pcall(function() worker = dfhack.job.getWorker(job) end)
      pcall(function() by_manager = job.flags.by_manager or false end)
      if not worker then nunassignedjobs = nunassignedjobs + 1 end
      if by_manager then nmanagerjobs = nmanagerjobs + 1 end
      if job.job_type == df.job_type.CustomReaction
          and tostring(job.reaction_name) == 'BREW_DRINK_FROM_PLANT' then
        nbrewjobs = nbrewjobs + 1
      end
    end
    link = link.next
  end
end)

local norders, norderleft = 0, 0
pcall(function()
  norders = #w.manager_orders.all
  for _, order in ipairs(w.manager_orders.all) do
    norderleft = norderleft + math.max(0, order.amount_left or 0)
  end
end)
local shop_summary, pending_summary = {}, {}
for _, name in ipairs(shop_names) do
  shop_summary[#shop_summary+1] = name .. ':' .. tostring(shops[name])
  pending_summary[#pending_summary+1] = name .. ':' .. tostring(pending_shops[name])
end

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

-- ---------------------------------------------------------------- threats & warnings
-- A policy cannot react to an attack it cannot see. Before this the observation carried
-- no danger signal at all, so "reacting to problems" was impossible in principle rather
-- than merely unimplemented.
local nhostile, ninjured, nannounce, ndanger = 0, 0, 0, 0
local warn = {}
pcall(function()
  for _, u in ipairs(w.units.active) do
    local ok = pcall(function()
      if dfhack.units.isDead(u) then return end
      -- hostile = alive, not ours, and either an invader or an active enemy
      local mine = dfhack.units.isCitizen(u)
      if not mine then
        local hostile = false
        pcall(function() hostile = dfhack.units.isInvader(u) end)
        if not hostile then pcall(function() hostile = dfhack.units.isDanger(u) end) end
        if hostile then nhostile = nhostile + 1 end
      else
        -- injured citizen: any bleeding or missing/broken part shows as a wound
        local hurt = false
        pcall(function() hurt = (#u.body.wounds > 0) end)
        if not hurt then pcall(function() hurt = (u.body.blood_count < u.body.blood_max) end) end
        if hurt then ninjured = ninjured + 1 end
      end
    end)
    if not ok then break end
  end
end)

-- The game's own announcement feed is where sieges, ambushes, deaths and cave-ins are
-- reported. We surface a count plus the most recent lines so a policy can branch, and
-- the replay can show WHEN the fort was told something was wrong.
pcall(function()
  local anns = w.status.announcements
  nannounce = #anns
  local from = math.max(0, nannounce - 12)
  for i = from, nannounce - 1 do
    local a = anns[i]
    local txt = ""
    pcall(function() txt = a.text or "" end)
    local low = txt:lower()
    if low:find("ambush") or low:find("siege") or low:find("attack") or low:find("has come")
       or low:find("slain") or low:find("struck down") or low:find("cancel") then
      ndanger = ndanger + 1
      if #warn < 4 then warn[#warn+1] = (txt:gsub("[|=%s]+", "_")):sub(1, 48) end
    end
  end
end)

print(string.format("OBS t=%d ncit=%d ndead=%d hsum=%d tsum=%d strsum=%d strdang=%d nfood=%d ndrink=%d nbuild=%d worders=%d nsolid=%d nbbox=%d nwood=%d nboulder=%d nblocks=%d nbars=%d nbeds=%d nbarrels=%d nseeds=%d nplants=%d nworkshop=%d nbuiltshop=%d nunbuiltshop=%d nfarmplots=%d shops=%s pending_shops=%s njobs=%d nunassignedjobs=%d nmanagerjobs=%d nbrewjobs=%d norders=%d norderleft=%d nhostile=%d ninjured=%d nannounce=%d ndanger=%d warn=%s nwild=%d nitems=%d nunits=%d cids=%s",
  tickabs, ncit, ndead, hsum, tsum, strsum, strdang, nfood, ndrink, nbuild, worders,
  nsolid, nbbox, stock.WOOD, stock.BOULDER, stock.BLOCKS, stock.BAR, stock.BED,
  stock.BARREL, stock.SEEDS, stock.PLANT, nworkshop, nbuiltshop, nunbuiltshop, nfarmplots,
  table.concat(shop_summary, ','), table.concat(pending_summary, ','),
  njobs, nunassignedjobs, nmanagerjobs, nbrewjobs, norders,
  norderleft, nhostile, ninjured, nannounce, ndanger,
  (#warn > 0 and table.concat(warn, ";") or "none"),
  (function() local n=0; pcall(function() for _,u in ipairs(w.units.active) do if dfhack.units.isWildlife(u) then n=n+1 end end end); return n end)(),
  #w.items.all, #w.units.all, table.concat(cids, ",")))
