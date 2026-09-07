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
local nbuild, nbuild_all, ndead, worders = 0, 0, 0, 0
-- What the fort BUILT, which is not the same as what is in buildings.all.
--
-- `#w.buildings.all` counts every record: on region3-lab that is 1597 entries of which
-- 223 are civzones, 14 stockpiles, 225 doors, 217 beds, 204 tables. A zone and a
-- stockpile cost nothing at all in DF -- no material, no job, no dwarf-time -- so
-- counting them made the development term farmable, worse than the tree exploit was.
-- Measured: a policy that does NOTHING but call create_zone once a round scored
-- composite 0.585504 with dug=0 and orders=0, against a do-nothing floor of 0.467857
-- and a best-tier 0.587811 -- 98% of the reference score for free.
--
-- So: finished buildings only, and not the two kinds that are placed rather than built.
-- Furniture stays counted: a bed needs an item and a dwarf to install it. Unfinished
-- buildings are intent, not effect, and an agent can plan them by the hundred.
-- The raw figure survives as nbuild_all, because losing a number is how a defect hides.
pcall(function() nbuild_all = #w.buildings.all end)
pcall(function()
  for _, b in ipairs(w.buildings.all) do
    pcall(function()
      local ty = b:getType()
      if ty ~= df.building_type.Civzone and ty ~= df.building_type.Stockpile then
        local finished = true
        pcall(function() finished = b:getBuildStage() >= b:getMaxBuildStage() end)
        if finished then nbuild = nbuild + 1 end
      end
    end)
  end
end)
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

-- How much storage the fort already has. Without it a policy cannot tell a seven-dwarf
-- embark with nowhere to put food from an established fort with piles everywhere, and it
-- opens both the same way. Measured on region3-lab by ablation: the reference tier's
-- opening create_stockpile is what killed it -- a new food pile pulls hauling across the
-- whole fort, and with three Forgotten Beasts about that cost 13 of 136 dwarves against
-- the 2 that idling loses. Dropping that one call took losses to 2, survival 0.818 to
-- 0.971 and the composite 0.4949 to 0.5453. The fort could not say "I already have
-- storage", so nobody could ask.
local nworkshop, nbuiltshop, nunbuiltshop, nfarmplots, nstockpile = 0, 0, 0, 0, 0
local shop_names = { 'Carpenters', 'Masons', 'Still', 'Craftsdwarfs', 'Farmers' }
local shops, pending_shops = {}, {}
for _, name in ipairs(shop_names) do shops[name], pending_shops[name] = 0, 0 end
pcall(function()
  for _, b in ipairs(w.buildings.all) do
    if b:getType() == df.building_type.FarmPlot then nfarmplots = nfarmplots + 1 end
    if b:getType() == df.building_type.Stockpile then nstockpile = nstockpile + 1 end
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
  -- Rock and soil only, decided ONCE per process instead of per tile.
--
-- Two things live in this table. First the rule: a tree trunk is WALL-shaped, so felling
-- timber used to drain the solid count exactly as if the fort had mined -- measured with
-- mining OFF and no designation anywhere, chopping 15 trees scored dug=135 against the 87
-- the best development tier mines in a whole three-day episode. Excavation means removing
-- ground, not vegetation.
--
-- Second the cost. This scan is the single most expensive thing the observer does: on
-- region3-lab the pinned box is 139x129x81, about 1.9M tiles, and observation was 47% of
-- the whole episode at ~7s a call against 0.2s on the fresh embark. Asking
-- df.tiletype.attrs[...] per tile pays for a DFHack wrapper index 1.9M times a round.
-- Deciding it once into a plain Lua array and indexing that instead: 5332ms -> 1692ms,
-- 3.15x, with an identical count of 1497465. Building the table costs 5.5ms.
local SOLID_LUT = _G.BONSAI_SOLID_LUT
if not SOLID_LUT then
  SOLID_LUT = {}
  pcall(function()
    for i = 0, df.tiletype._last_item do
      local at = df.tiletype.attrs[i]
      if at then
        SOLID_LUT[i] = (at.shape == df.tiletype_shape.WALL
                        and at.material ~= df.tiletype_material.TREE
                        and at.material ~= df.tiletype_material.PLANT
                        and at.material ~= df.tiletype_material.MUSHROOM) or false
      end
    end
  end)
  _G.BONSAI_SOLID_LUT = SOLID_LUT
end

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
            if SOLID_LUT[tt[ix][iy]] then cnt = cnt + 1 end
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
local nhostile, nhostile_map, ninjured, nannounce, ndanger = 0, 0, 0, 0, 0
local nwounded, ncancel = 0, 0
local warn, cancels = {}, {}

-- How close something dangerous has to be before it is this fort's problem.
--
-- `isDanger` is a property of the CREATURE, not of the situation: on the fresh embark
-- it is true for four Hadrosaurid Fiends living in the caverns tens of levels down,
-- which the fort will never meet. Counting them made `under_threat` permanently true
-- from the first minute, and the reactive tier -- which stops expanding under threat --
-- therefore held for the whole episode and dug 13 tiles where the same policy unthrottled
-- digs 82. A threat channel that is always on carries no information and disables every
-- policy that believes it.
--
-- Proximity is the missing predicate. A creature five levels away and thirty tiles off
-- can be in the fort within a round; one in a cavern forty levels below cannot, and the
-- fort should not cower from it. Invaders are exempt: a siege on the map edge is exactly
-- the thing to react to BEFORE it arrives.
local THREAT_RADIUS_XY = 30
local THREAT_RADIUS_Z = 5

local citizens, suspects = {}, {}
pcall(function()
  for _, u in ipairs(w.units.active) do
    local ok = pcall(function()
      if dfhack.units.isDead(u) then return end
      if dfhack.units.isCitizen(u) then
        table.insert(citizens, { u.pos.x, u.pos.y, u.pos.z })
        -- Injured means NEEDING CARE, which is not the same as carrying a wound record.
        -- DF keeps a wound after it heals, so `#u.body.wounds > 0` counts scars: on the
        -- mature fort it reported 101 injured of 136 with ZERO of them bleeding and 40
        -- carrying nothing newer than a month, while DF's own health bookkeeping said two
        -- dwarves needed a doctor. A fort with a history read as a fort in crisis, which
        -- is the same mistake as counting cavern demons as hostiles: a state that is
        -- permanently true tells a policy nothing.
        pcall(function() if #u.body.wounds > 0 then nwounded = nwounded + 1 end end)
        local hurt = false
        pcall(function() hurt = u.health.flags.needs_healthcare end)
        if not hurt then pcall(function() hurt = (u.body.blood_count < u.body.blood_max) end) end
        if hurt then ninjured = ninjured + 1 end
      else
        local invader, danger = false, false
        pcall(function() invader = dfhack.units.isInvader(u) end)
        pcall(function() danger = dfhack.units.isDanger(u) end)
        if invader or danger then
          table.insert(suspects, { u.pos.x, u.pos.y, u.pos.z, invader })
        end
      end
    end)
    if not ok then break end
  end
end)

pcall(function()
  for _, s in ipairs(suspects) do
    nhostile_map = nhostile_map + 1
    local near = s[4]                                  -- invaders count from anywhere
    if not near then
      for _, c in ipairs(citizens) do
        if math.abs(s[3] - c[3]) <= THREAT_RADIUS_Z
            and math.abs(s[1] - c[1]) <= THREAT_RADIUS_XY
            and math.abs(s[2] - c[2]) <= THREAT_RADIUS_XY then
          near = true
          break
        end
      end
    end
    if near then nhostile = nhostile + 1 end
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
    -- A cancelled job is NOT danger. `cancel` used to sit in this list, and on any fort
    -- that is actually working the cancellation feed never stops: "Miner cancels Carve
    -- downward: Damp stone", "cancels Dig: Inappropriate". Those four lines filled the
    -- twelve-announcement window, drove ndanger up every round and latched `under_threat`
    -- on for the rest of the episode -- so even with the wildlife miscount fixed, the
    -- reactive tier still held for good. Real danger and failed work are different
    -- questions and the policy must be able to ask them separately: a fort whose digging
    -- keeps being cancelled needs to dig SOMEWHERE ELSE, which is the opposite of the
    -- hunker-down response that danger calls for.
    if low:find("cancel") then
      ncancel = ncancel + 1
      if #cancels < 4 then cancels[#cancels+1] = (txt:gsub("[|=%s;]+", "_")):sub(1, 48) end
    elseif low:find("ambush") or low:find("siege") or low:find("attack")
       or low:find("has come") or low:find("slain") or low:find("struck down") then
      ndanger = ndanger + 1
      if #warn < 4 then warn[#warn+1] = (txt:gsub("[|=%s;]+", "_")):sub(1, 48) end
    end
  end
end)

print(string.format("OBS t=%d ncit=%d ndead=%d hsum=%d tsum=%d strsum=%d strdang=%d nfood=%d ndrink=%d nbuild=%d nbuild_all=%d worders=%d nsolid=%d nbbox=%d nwood=%d nboulder=%d nblocks=%d nbars=%d nbeds=%d nbarrels=%d nseeds=%d nplants=%d nworkshop=%d nbuiltshop=%d nunbuiltshop=%d nfarmplots=%d nstockpile=%d shops=%s pending_shops=%s njobs=%d nunassignedjobs=%d nmanagerjobs=%d nbrewjobs=%d norders=%d norderleft=%d nhostile=%d nhostile_map=%d ninjured=%d nwounded=%d nannounce=%d ndanger=%d ncancel=%d warn=%s cancels=%s nwild=%d nitems=%d nunits=%d cids=%s",
  tickabs, ncit, ndead, hsum, tsum, strsum, strdang, nfood, ndrink, nbuild, nbuild_all, worders,
  nsolid, nbbox, stock.WOOD, stock.BOULDER, stock.BLOCKS, stock.BAR, stock.BED,
  stock.BARREL, stock.SEEDS, stock.PLANT, nworkshop, nbuiltshop, nunbuiltshop, nfarmplots, nstockpile,
  table.concat(shop_summary, ','), table.concat(pending_summary, ','),
  njobs, nunassignedjobs, nmanagerjobs, nbrewjobs, norders,
  norderleft, nhostile, nhostile_map, ninjured, nwounded, nannounce, ndanger, ncancel,
  (#warn > 0 and table.concat(warn, ";") or "none"),
  (#cancels > 0 and table.concat(cancels, ";") or "none"),
  (function() local n=0; pcall(function() for _,u in ipairs(w.units.active) do if dfhack.units.isWildlife(u) then n=n+1 end end end); return n end)(),
  #w.items.all, #w.units.all, table.concat(cids, ",")))
