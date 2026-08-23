-- Map-track capture for the episode recorder.
--
-- Writes ONE snapshot as a single JSON line to a file (not to stdout): a keyframe
-- carries the whole fort region, a delta carries only the tiles that changed. The
-- previous tile buffer lives in a Lua global, which survives between separate
-- dfhack-run RPC calls (verified live 2026-07-29) — so the delta costs no extra reads.
--
-- Cadence is the caller's business. Measured costs that shaped this:
--     tiles blockwise   ~30ms   (25600 tiles)  -> sample rarely, walls barely move
--     units             ~0ms    (54 units)     -> sample often, dwarves are the motion
--     items             ~2-9ms  (67 in range)
--
-- Args (via map_capture_args.txt, one value per line): mode(kf|d), out_path
-- Emits to stdout only: "MAPCAP ok=1 bytes=N kind=kf|d tiles=N changed=N"
-- mode and output path arrive as script arguments. Parallel episodes share this DF
-- directory, so a single args file would have one fort dictating another's capture.
local a1, a2, a3 = ...
local mode = (a1 and #a1 > 0) and a1 or 'kf'
local out = (a2 and #a2 > 0) and a2 or '/srv/df-bonsai/current/map_capture.jsonl'

local w = df.global.world
local m = w.map
local G = _G

-- ---------------------------------------------------------------- fort bounding box
-- Never capture the whole 192x192x66 map: the fort occupies a small part of it, and
-- the bbox is what keeps a snapshot at ~30ms / ~53KB instead of ~1.9s / megabytes.
local xs, ys, zs = {}, {}, {}
local function note(x, y, z) xs[#xs+1] = x; ys[#ys+1] = y; zs[#zs+1] = z end
-- Optional exact audit viewport: x,y,z,width,height,depth. Normal recordings omit it
-- and retain the whole-fort bounding box. This lets fidelity checks photograph a
-- mature 65-z-level fort without serialising a million tiles for every close-up.
local exact = nil
if a3 and #a3 > 0 then
  local v = {}
  for n in string.gmatch(a3, '[^,]+') do v[#v+1] = tonumber(n) end
  if #v == 6 then
    exact = v
    note(v[1], v[2], v[3]); note(v[1]+v[4]-1, v[2]+v[5]-1, v[3]+v[6]-1)
  end
end
if not exact then
  pcall(function()
    for _, u in ipairs(dfhack.units.getCitizens(true)) do note(u.pos.x, u.pos.y, u.pos.z) end
  end)
  pcall(function()
    for _, b in ipairs(w.buildings.all) do note(b.x1, b.y1, b.z); note(b.x2, b.y2, b.z) end
  end)
end
if #xs == 0 then
  print('MAPCAP ok=0 reason=no_anchor')
  return
end
local function span(t, pad, cap)
  local lo, hi = t[1], t[1]
  for _, v in ipairs(t) do if v < lo then lo = v end; if v > hi then hi = v end end
  return math.max(0, lo - pad), math.min(cap - 1, hi + pad)
end
local x0, x1 = span(xs, exact and 0 or 24, m.x_count)
local y0, y1 = span(ys, exact and 0 or 24, m.y_count)
local z0, z1 = span(zs, exact and 0 or 2, m.z_count)

-- STICKY bbox: only ever grow it. Citizens wander, so a bbox recomputed from scratch
-- drifts every few hundred ticks, and every drift invalidates the delta buffer and
-- forces a full keyframe (observed live: a delta at t+1200 had to fall back to a
-- 55KB keyframe purely because the region moved). Growing-only keeps deltas valid for
-- long stretches; growth is bounded in practice because citizens stay near the fort.
if not exact then
  local p = _G.BONSAI_MAP_BOX
  if p then
    x0, y0, z0 = math.min(x0, p[1]), math.min(y0, p[2]), math.min(z0, p[3])
    x1, y1, z1 = math.max(x1, p[4]), math.max(y1, p[5]), math.max(z1, p[6])
  end
  _G.BONSAI_MAP_BOX = { x0, y0, z0, x1, y1, z1 }
end

-- block-align so we can fetch each 16x16 block once (per-tile getTileBlock measured
-- 39-49ms vs 28-30ms blockwise for the same region)
local bx0, bx1 = math.floor(x0 / 16), math.floor(x1 / 16)
local by0, by1 = math.floor(y0 / 16), math.floor(y1 / 16)
local gx0, gx1 = bx0 * 16, bx1 * 16 + 15
local gy0, gy1 = by0 * 16, by1 * 16 + 15
local W, H, D = gx1 - gx0 + 1, gy1 - gy0 + 1, z1 - z0 + 1

-- Exact per-tile palette row. An external geology dump is tied to one save and silently
-- paints another fort with the wrong stone colours. Resolve the loaded save here and
-- carry the compact row alongside the tiletype, including constructed walls/floors.
local MAT_ROW = {}
local function palette_row_of(mt, mi)
  mt, mi = tonumber(mt) or -1, tonumber(mi) or -1
  local key = mt .. ':' .. mi
  if MAT_ROW[key] ~= nil then return MAT_ROW[key] end
  local row = 0
  pcall(function()
    local info = dfhack.matinfo.decode(mt, mi)
    if info and info.material then row = (info.material.state_color.Solid or -1) + 1 end
  end)
  if row < 0 or row > 136 then row = 0 end
  MAT_ROW[key] = row
  return row
end
local CONSTRUCTION_ROW = {}
local function pkey(x, y, z) return x .. ',' .. y .. ',' .. z end
pcall(function()
  for _, construction in ipairs(w.event.constructions) do
    local p = construction.pos
    CONSTRUCTION_ROW[pkey(p.x, p.y, p.z)] =
      palette_row_of(construction.mat_type, construction.mat_index)
  end
end)
local function block_geo(bx, by, z)
  local ok, gi = pcall(function()
    return dfhack.maps.getRegionBiome(
      dfhack.maps.getTileBiomeRgn(bx * 16, by * 16, z)).geo_index
  end)
  return ok and gi or nil
end

-- ---------------------------------------------------------------- tiles (row-major)
-- Layout the renderer relies on: z outer, then y, then x. Index is 1-based and dense.
--
-- `hidden` rides along with the tiletype. It is not a detail: it is FOG OF WAR, and
-- without it a replay shows the player things the player could not see. Measured on the
-- pinned save at embark — z=49 27.2% hidden, z=48 95.6%, z=47 and everything below
-- 100.0% — so a recording that ignores it renders an entire undiscovered rock layer as
-- solid terrain where the game shows black. It cannot be reconstructed after the fact
-- either: guessing "revealed if next to open space" agreed with the engine on only
-- 31-96% of tiles depending on the level, and erred towards revealing.
local tiles, hid, liq, pal = {}, {}, {}, {}
local n = 0
for z = z0, z1 do
  for by = by0, by1 do
    for bx = bx0, bx1 do
      local blk = dfhack.maps.getTileBlock(bx * 16, by * 16, z)
      local ox, oy = bx * 16 - gx0, by * 16 - gy0
      local veins, geo = {}, blk and block_geo(bx, by, z) or nil
      if blk then
        for i = 0, #blk.block_events - 1 do
          local ev = blk.block_events[i]
          pcall(function()
            if ev.tile_bitmask and ev.inorganic_mat then
              veins[#veins + 1] = { ev.tile_bitmask, ev.inorganic_mat }
            end
          end)
        end
      end
      for iy = 0, 15 do
        local row = (z - z0) * W * H + (oy + iy) * W + ox
        if blk then
          local tt, des = blk.tiletype, blk.designation
          for ix = 0, 15 do
            tiles[row + ix + 1] = tt[ix][iy]
            local d = des[ix][iy]
            hid[row + ix + 1] = d.hidden and 1 or 0
            local depth = tonumber(d.flow_size) or 0
            local ltype = d.liquid_type == true and 1 or tonumber(d.liquid_type) or 0
            liq[row + ix + 1] = depth + (ltype ~= 0 and 8 or 0)
            local x, y = bx * 16 + ix, by * 16 + iy
            local prow = CONSTRUCTION_ROW[pkey(x, y, z)]
            if prow == nil then
              local mi
              for k = 1, #veins do
                local bm, vmat = veins[k][1], veins[k][2]
                local okb, hit = pcall(function()
                  return bit32 and bit32.band(bm.bits[iy], bit32.lshift(1, ix)) ~= 0
                    or (bm.bits[iy] >> ix) % 2 == 1
                end)
                if okb and hit then mi = vmat end
              end
              if mi == nil and geo then
                pcall(function()
                  local layer = d.geolayer_index
                  mi = w.world_data.geo_biomes[geo].layers[layer].mat_index
                end)
              end
              prow = palette_row_of(0, mi)
            end
            pal[row + ix + 1] = prow or 0
          end
        else
          -- no block loaded means nothing is there to see, which is also unseen
          for ix = 0, 15 do
            tiles[row + ix + 1] = 0; hid[row + ix + 1] = 1
            liq[row + ix + 1] = 0; pal[row + ix + 1] = 0
          end
        end
      end
      n = n + 256
    end
  end
end

-- ---------------------------------------------------------------- geometry guard
-- If the fort grows, the bbox moves and old deltas no longer describe the same grid.
-- Emit a fresh keyframe rather than a delta against an incompatible buffer.
local geo = string.format('%d,%d,%d,%d,%d,%d', gx0, gy0, gx1, gy1, z0, z1)
if mode == 'd' and (G.BONSAI_MAP_GEO ~= geo or not G.BONSAI_MAP_PREV) then mode = 'kf' end

local body, ntiles, nchanged = {}, #tiles, 0
if mode == 'kf' then
  -- run-length encode: fort maps are overwhelmingly repeated stone/air
  local runs = {}
  local cur, cnt = tiles[1], 0
  for i = 1, ntiles do
    local v = tiles[i]
    if v == cur then cnt = cnt + 1 else runs[#runs+1] = cur .. ',' .. cnt; cur = v; cnt = 1 end
  end
  runs[#runs+1] = cur .. ',' .. cnt
  body[#body+1] = '"rle":[' .. table.concat(runs, ',') .. ']'
else
  local prev = G.BONSAI_MAP_PREV
  local ch = {}
  for i = 1, ntiles do
    if tiles[i] ~= prev[i] then ch[#ch+1] = (i - 1) .. ',' .. tiles[i]; nchanged = nchanged + 1 end
  end
  body[#body+1] = '"set":[' .. table.concat(ch, ',') .. ']'
end
G.BONSAI_MAP_PREV = tiles
G.BONSAI_MAP_GEO = geo

-- The fog mask goes out RLE'd on every snapshot, keyframe or delta. It is two values
-- over a mostly-uniform grid, so it costs a few hundred bytes even on a big fort, and
-- sending it whole avoids a second delta buffer that could fall out of step with the
-- tiletype one and silently reveal the map.
do
  local runs, cur, cnt = {}, hid[1], 0
  for i = 1, ntiles do
    if hid[i] == cur then cnt = cnt + 1
    else runs[#runs + 1] = cur .. ',' .. cnt; cur = hid[i]; cnt = 1 end
  end
  runs[#runs + 1] = cur .. ',' .. cnt
  body[#body + 1] = '"hrle":[' .. table.concat(runs, ',') .. ']'
end

-- Liquid is part of the visible map, not an item. Pack depth (1..7) in the low three
-- bits and magma in bit 3. This preserves shallow-vs-deep water and lets both renderers
-- use DF's WATER/MAGMA art; old recordings simply have no lrle and remain dry.
do
  local runs, cur, cnt = {}, liq[1], 0
  for i = 1, ntiles do
    if liq[i] == cur then cnt = cnt + 1
    else runs[#runs + 1] = cur .. ',' .. cnt; cur = liq[i]; cnt = 1 end
  end
  runs[#runs + 1] = cur .. ',' .. cnt
  body[#body + 1] = '"lrle":[' .. table.concat(runs, ',') .. ']'
end

-- Material colour is fixed for almost every natural tile. Carry a full RLE only on a
-- keyframe, then the handful of construction changes as index/value pairs. A mature
-- 160x144x73 fort produced a 443k-value full palette track; repeating that every delta
-- would consume the entire recording budget in two frames.
if mode == 'kf' or not G.BONSAI_MAP_PAL then
  local runs, cur, cnt = {}, pal[1], 0
  for i = 1, ntiles do
    if pal[i] == cur then cnt = cnt + 1
    else runs[#runs + 1] = cur .. ',' .. cnt; cur = pal[i]; cnt = 1 end
  end
  runs[#runs + 1] = cur .. ',' .. cnt
  body[#body + 1] = '"prle":[' .. table.concat(runs, ',') .. ']'
else
  local changed, prev = {}, G.BONSAI_MAP_PAL
  for i = 1, ntiles do
    if pal[i] ~= prev[i] then changed[#changed + 1] = (i - 1) .. ',' .. pal[i] end
  end
  body[#body + 1] = '"pset":[' .. table.concat(changed, ',') .. ']'
end
G.BONSAI_MAP_PAL = pal

-- ------------------------------------------------------ renderer transition state
-- Map tiletypes are not enough to reproduce Premium graphics. DF has already chosen
-- floor edging selectors, ramp topology and wall/ramp shadows for the visible viewport.
-- Preserve those packed decisions verbatim. The arrays in graphic_viewportst are
-- x-major (the indexing used by DFHack's devel/inspect-screen); the JSON below is
-- deliberately converted to normal row-major order for the replay renderers.
--
-- This covers only the currently rendered viewport. The full semantic map remains in
-- rle/set and is the fallback for old recordings and cells that were off screen.
local function viewport_transition_json()
  local ok, result = pcall(function()
    if not dfhack.screen.inGraphicsMode() then return nil end
    local gps, vp = df.global.gps, df.global.gps.main_viewport
    local vw, vh = tonumber(vp.dim_x) or 0, tonumber(vp.dim_y) or 0
    if vw <= 0 or vh <= 0 then return nil end
    local function value(vec, i)
      local good, v = pcall(function() return tonumber(vec[i]) end)
      return good and v or 0
    end
    local function rle(values)
      local runs, cur, cnt = {}, values[1] or 0, 0
      for i = 1, #values do
        local v = values[i]
        if v == cur then cnt = cnt + 1
        else runs[#runs+1] = tostring(cur); runs[#runs+1] = tostring(cnt); cur = v; cnt = 1 end
      end
      runs[#runs+1] = tostring(cur); runs[#runs+1] = tostring(cnt)
      return '[' .. table.concat(runs, ',') .. ']'
    end
    local bg, bg2, floor, ramp, shadow, top = {}, {}, {}, {}, {}, {}
    for sy = 0, vh - 1 do
      for sx = 0, vw - 1 do
        local src = sx * vh + sy
        local dst = sy * vw + sx + 1
        bg[dst] = value(vp.screentexpos_background, src)
        bg2[dst] = value(vp.screentexpos_background_two, src)
        floor[dst] = value(vp.screentexpos_floor_flag, src)
        ramp[dst] = value(vp.screentexpos_ramp_flag, src)
        shadow[dst] = value(vp.screentexpos_shadow_flag, src)
        top[dst] = value(vp.screentexpos_top_shadow, src)
      end
    end
    -- texpos ids change whenever DF reloads textures. Resolve only the ids used by
    -- this viewport to stable vanilla raw page/cell coordinates.
    local wanted, refs = {}, {}
    for _, values in ipairs({bg, bg2, top}) do
      for i = 1, #values do if values[i] and values[i] > 0 then wanted[values[i]] = true end end
    end
    local seen = {}
    local function quote(s)
      return '"' .. tostring(s or ''):gsub('\\', '\\\\'):gsub('"', '\\"') .. '"'
    end
    local function scan_page(page, vec)
      local width = tonumber(page.page_dim_x) or 0
      if width <= 0 or not vec then return end
      for i = 0, #vec - 1 do
        local id = tonumber(vec[i]) or 0
        if wanted[id] and not seen[id] then
          refs[#refs + 1] = string.format('[%d,%s,%d,%d]', id, quote(page.token),
            i % width, math.floor(i / width))
          seen[id] = true
        end
      end
    end
    for _, page in ipairs(df.global.texture.page) do
      scan_page(page, page.texpos)
      scan_page(page, page.texpos_gs)
    end
    table.sort(refs)
    return string.format(
      '{"origin":[%d,%d,%d],"dims":[%d,%d],"bgrle":%s,"bg2rle":%s,' ..
      '"frle":%s,"rrle":%s,"srle":%s,"trle":%s,"tex":%s}',
      df.global.window_x, df.global.window_y, df.global.window_z, vw, vh,
      rle(bg), rle(bg2), rle(floor), rle(ramp), rle(shadow), rle(top),
      '[' .. table.concat(refs, ',') .. ']')
  end)
  return ok and result or nil
end
local viewport_transition = viewport_transition_json()
if viewport_transition then body[#body + 1] = '"viewport":' .. viewport_transition end

-- ---------------------------------------------------------------- entities
local function join(t) return '[' .. table.concat(t, ',') .. ']' end
local function esc(s)
  return (tostring(s or ''):gsub('\\', '\\\\'):gsub('"', '\\"'):gsub('[\n\r\t]', ' '))
end
local function number_or(f, fallback)
  local ok, v = pcall(f)
  v = ok and tonumber(v) or nil
  return v == nil and fallback or v
end
-- Compact material class used to choose the same furniture/item family DF chooses.
-- 0 unknown/organic, 1 wood, 2 stone, 3 metal, 4 glass.
local function material_class(mt, mi)
  local cls = 0
  pcall(function()
    local info = dfhack.matinfo.decode(mt, mi)
    if not info then return end
    local flags = info.material and info.material.flags
    if flags and flags.IS_METAL then cls = 3
    elseif flags and (flags.IS_GLASS or flags.CRYSTAL_GLASSABLE) then cls = 4
    elseif info.plant then cls = 1
    elseif info.inorganic then cls = 2 end
  end)
  return cls
end
local function material_row(mt, mi)
  return palette_row_of(mt, mi)
end

local us = {}
pcall(function()
  for _, u in ipairs(w.units.active) do
    local job = -1
    pcall(function()
      local j = u.job.current_job
      if j then job = j.job_type end
    end)
    local dead = 0
    pcall(function() if dfhack.units.isDead(u) then dead = 1 end end)
    -- Citizen flag: without it a viewer cannot tell the seven dwarves from the
    -- wandering wildlife, since both can carry profession STANDARD.
    local cit = 0
    pcall(function() if dfhack.units.isCitizen(u) then cit = 1 end end)
    -- race is what lets a viewer draw the right creature sprite; without it every
    -- animal has to be a generic marker
    local creature, caste = '', ''
    pcall(function()
      local raw = w.raws.creatures.all[u.race]
      if raw then
        creature = raw.creature_id or ''
        local craw = raw.caste and raw.caste[u.caste]
        if craw then caste = craw.caste_id or '' end
      end
    end)
    us[#us+1] = string.format('[%d,%d,%d,%d,%d,%d,%d,%d,%d,"%s","%s"]',
      u.id, u.pos.x, u.pos.y, u.pos.z, u.profession, job, dead, cit, u.race or -1,
      esc(creature), esc(caste))
  end
end)

local bs = {}
pcall(function()
  for _, b in ipairs(w.buildings.all) do
    local subtype = number_or(function() return b:getSubtype() end, -1)
    local custom = number_or(function() return b:getCustomType() end, -1)
    local stage = number_or(function() return b.build_stage end, -1)
    local maxstage = number_or(function() return b.max_build_stage end, -1)
    local mt = number_or(function() return b.mat_type end, -1)
    local mi = number_or(function() return b.mat_index end, -1)
    bs[#bs+1] = string.format('[%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d]',
      b.id, b:getType(), b.x1, b.y1, b.x2, b.y2, b.z, subtype, custom,
      stage, maxstage, mt, mi, material_class(mt, mi), material_row(mt, mi))
  end
end)

local its = {}
pcall(function()
  for _, it in ipairs(w.items.all) do
    local ok, ty = pcall(function() return it:getType() end)
    local visible = true
    pcall(function()
      -- `pos` is also populated for workshop inputs and building components. They
      -- all collapse onto the workshop centre even though DF does not draw them as
      -- ground items. `on_ground` is the positive visibility signal; the negative
      -- flags alone let hundreds of contained objects leak into one screen cell.
      visible = it.flags.on_ground and not (it.flags.in_inventory or it.flags.in_building
                     or it.flags.removed or it.flags.garbage_collect)
    end)
    if ok and visible and it.pos.x >= gx0 and it.pos.x <= gx1
        and it.pos.y >= gy0 and it.pos.y <= gy1
        and it.pos.z >= z0 and it.pos.z <= z1 then
      local subtype = number_or(function() return it:getSubtype() end, -1)
      local mt = number_or(function() return it:getMaterial() end,
        number_or(function() return it.mat_type end, -1))
      local mi = number_or(function() return it:getMaterialIndex() end,
        number_or(function() return it.mat_index end, -1))
      local quality = number_or(function() return it:getQuality() end, 0)
      local stack = number_or(function() return it:getStackSize() end,
        number_or(function() return it.stack_size end, 1))
      local creature = ''
      pcall(function()
        local race = tonumber(it.race) or -1
        if race < 0 and (ty == df.item_type.FISH or ty == df.item_type.FISH_RAW) then
          race = subtype
        end
        local raw = race >= 0 and w.raws.creatures.all[race] or nil
        if raw then creature = raw.creature_id or '' end
      end)
      its[#its+1] = string.format('[%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,"%s",1]',
        it.id, ty, it.pos.x, it.pos.y, it.pos.z, subtype, mt, mi, quality, stack,
        material_class(mt, mi), material_row(mt, mi), esc(creature))
    end
  end
end)

-- ---------------------------------------------------------------- emit
local line = string.format(
  '{"kind":"%s","tick":%d,"dfv":"%s","origin":[%d,%d,%d],"dims":[%d,%d,%d],%s,"units":%s,"blds":%s,"items":%s}',
  mode, df.global.cur_year * 1000000 + df.global.cur_year_tick,
  esc(dfhack.getDFVersion()), gx0, gy0, z0, W, H, D,
  table.concat(body, ','), join(us), join(bs), join(its))

local f = io.open(out, 'a')
if not f then print('MAPCAP ok=0 reason=cannot_open'); return end
f:write(line, '\n'); f:close()
print(string.format('MAPCAP ok=1 bytes=%d kind=%s tiles=%d changed=%d units=%d blds=%d items=%d',
  #line, mode, ntiles, nchanged, #us, #bs, #its))
