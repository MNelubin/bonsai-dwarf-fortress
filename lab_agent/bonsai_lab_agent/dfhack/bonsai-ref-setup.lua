-- Competent REFERENCE policy setup (deterministic development actions applied at T0).
-- Robust: every action pcall-guarded; prints REFSETUP <what-succeeded>.
local w = df.global.world
local rep = {}

-- 1. enable key production labors on every citizen
pcall(function()
  local L = df.unit_labor
  local labors = {L.MINE, L.BREWER, L.COOK, L.CARPENTER, L.MASON, L.CUTWOOD,
                  L.PLANT, L.HAUL_FOOD, L.HAUL_ITEM, L.HAUL_WOOD, L.HAUL_STONE}
  local n = 0
  for _, u in ipairs(dfhack.units.getCitizens(true)) do
    for _, l in ipairs(labors) do pcall(function() u.status.labors[l] = true end) end
    n = n + 1
  end
  rep[#rep+1] = "labors="..n
end)

-- 2. queue manager work orders (brew drink, cook meal) -> worders + drink/food over time
pcall(function()
  local function addorder(jt, amount)
    local mo = df.manager_order:new()
    pcall(function() mo.id = w.manager_orders.manager_order_next_id; w.manager_orders.manager_order_next_id = mo.id + 1 end)
    mo.job_type = jt
    pcall(function() mo.item_type = -1 end); pcall(function() mo.item_subtype = -1 end)
    pcall(function() mo.mat_type = -1 end); pcall(function() mo.mat_index = -1 end)
    mo.amount_left = amount; mo.amount_total = amount
    pcall(function() mo.frequency = df.manager_order.T_frequency.OneTime end)
    w.manager_orders.all:insert('#', mo)
  end
  addorder(df.job_type.BrewDrink, 30)
  addorder(df.job_type.PrepareMeal, 30)
  rep[#rep+1] = "orders="..#w.manager_orders.all
end)

-- 3. designate a down-stair + surrounding dig near the first citizen (dug_tiles + mining)
pcall(function()
  local u = dfhack.units.getCitizens(true)[1]
  if not u then return end
  local x, y, z = u.pos.x, u.pos.y, u.pos.z
  local dug = 0
  for dz = 0, 4 do
    for dx = -2, 2 do for dy = -2, 2 do
      pcall(function()
        local tt = dfhack.maps.getTileType(x+dx, y+dy, z-dz)
        if tt then
          local des = dfhack.maps.getTileFlags(x+dx, y+dy, z-dz)
          if des then des.dig = df.tile_dig_designation.Default; dug = dug + 1 end
        end
      end)
    end end
  end
  rep[#rep+1] = "dig="..dug
end)

-- 4. build several stockpiles near the citizen (immediate, deterministic nbuild + organization)
pcall(function()
  local u = dfhack.units.getCitizens(true)[1]
  if not u then return end
  local built = 0
  for i = 0, 4 do
    pcall(function()
      local b = dfhack.buildings.constructBuilding{
        type = df.building_type.Stockpile, abstract = true,
        pos = {x = u.pos.x + 3 + i*3, y = u.pos.y, z = u.pos.z},
        width = 2, height = 2}
      if b then built = built + 1 end
    end)
  end
  rep[#rep+1] = "stockpiles="..built
end)

print("REFSETUP "..table.concat(rep, " "))
