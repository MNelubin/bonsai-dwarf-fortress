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
local a1, a2 = ...
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
pcall(function()
  for _, u in ipairs(dfhack.units.getCitizens(true)) do note(u.pos.x, u.pos.y, u.pos.z) end
end)
pcall(function()
  for _, b in ipairs(w.buildings.all) do note(b.x1, b.y1, b.z); note(b.x2, b.y2, b.z) end
end)
if #xs == 0 then
  print('MAPCAP ok=0 reason=no_anchor')
  return
end
local function span(t, pad, cap)
  local lo, hi = t[1], t[1]
  for _, v in ipairs(t) do if v < lo then lo = v end; if v > hi then hi = v end end
  return math.max(0, lo - pad), math.min(cap - 1, hi + pad)
end
local x0, x1 = span(xs, 24, m.x_count)
local y0, y1 = span(ys, 24, m.y_count)
local z0, z1 = span(zs, 2, m.z_count)

-- STICKY bbox: only ever grow it. Citizens wander, so a bbox recomputed from scratch
-- drifts every few hundred ticks, and every drift invalidates the delta buffer and
-- forces a full keyframe (observed live: a delta at t+1200 had to fall back to a
-- 55KB keyframe purely because the region moved). Growing-only keeps deltas valid for
-- long stretches; growth is bounded in practice because citizens stay near the fort.
do
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

-- ---------------------------------------------------------------- tiles (row-major)
-- Layout the renderer relies on: z outer, then y, then x. Index is 1-based and dense.
local tiles = {}
local n = 0
for z = z0, z1 do
  for by = by0, by1 do
    for bx = bx0, bx1 do
      local blk = dfhack.maps.getTileBlock(bx * 16, by * 16, z)
      local ox, oy = bx * 16 - gx0, by * 16 - gy0
      for iy = 0, 15 do
        local row = (z - z0) * W * H + (oy + iy) * W + ox
        if blk then
          local tt = blk.tiletype
          for ix = 0, 15 do tiles[row + ix + 1] = tt[ix][iy] end
        else
          for ix = 0, 15 do tiles[row + ix + 1] = 0 end
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

-- ---------------------------------------------------------------- entities
local function join(t) return '[' .. table.concat(t, ',') .. ']' end

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
    us[#us+1] = string.format('[%d,%d,%d,%d,%d,%d,%d,%d,%d]',
      u.id, u.pos.x, u.pos.y, u.pos.z, u.profession, job, dead, cit, u.race or -1)
  end
end)

local bs = {}
pcall(function()
  for _, b in ipairs(w.buildings.all) do
    bs[#bs+1] = string.format('[%d,%d,%d,%d,%d,%d,%d]',
      b.id, b:getType(), b.x1, b.y1, b.x2, b.y2, b.z)
  end
end)

local its = {}
pcall(function()
  for _, it in ipairs(w.items.all) do
    local ok, ty = pcall(function() return it:getType() end)
    if ok and it.pos.z >= z0 and it.pos.z <= z1 then
      its[#its+1] = string.format('[%d,%d,%d,%d,%d]', it.id, ty, it.pos.x, it.pos.y, it.pos.z)
    end
  end
end)

-- ---------------------------------------------------------------- emit
local line = string.format(
  '{"kind":"%s","tick":%d,"origin":[%d,%d,%d],"dims":[%d,%d,%d],%s,"units":%s,"blds":%s,"items":%s}',
  mode, df.global.cur_year * 1000000 + df.global.cur_year_tick,
  gx0, gy0, z0, W, H, D, table.concat(body, ','), join(us), join(bs), join(its))

local f = io.open(out, 'a')
if not f then print('MAPCAP ok=0 reason=cannot_open'); return end
f:write(line, '\n'); f:close()
print(string.format('MAPCAP ok=1 bytes=%d kind=%s tiles=%d changed=%d units=%d blds=%d items=%d',
  #line, mode, ntiles, nchanged, #us, #bs, #its))
