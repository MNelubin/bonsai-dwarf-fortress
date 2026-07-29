-- One-time dump of the DF enums the replay viewer needs to render a recording as a
-- readable fort rather than a grid of integers. Writes JSON to /tmp/bonsai_enums.json.
--
-- Recordings store raw ids (tiletype 261, profession 102, job 51) because that keeps
-- them small and lossless; this table turns those back into "smooth granite wall" and
-- "Miner". It is versioned WITH the DF build - a different DF renumbers these, which
-- is why regime_key already includes df_version.
--
-- Uses DFHack's _first_item/_last_item bounds rather than ipairs/pairs: iterating a
-- DFHack enum table generically hangs (the first attempt at this script timed out at
-- 60s), because those tables carry bidirectional mappings and metatables.
local out = '/tmp/bonsai_enums.json'
local parts = {}

local function esc(s)
  return (tostring(s or ''):gsub('\\', '\\\\'):gsub('"', '\\"'):gsub('[\n\r\t]', ' '))
end

local function bounds(enum, fallback_hi)
  local lo, hi = 0, fallback_hi
  pcall(function()
    if enum._first_item then lo = enum._first_item end
    if enum._last_item then hi = enum._last_item end
  end)
  return lo, math.min(hi, 4096)          -- hard cap: never let a bad bound run away
end

-- ---- tiletypes: id -> {caption, shape, material, variant, special}
do
  local lo, hi = bounds(df.tiletype, 1024)
  local rows, n = {}, 0
  for id = lo, hi do
    local ok = pcall(function()
      local a = df.tiletype.attrs[id]
      if a then
        rows[#rows+1] = string.format(
          '"%d":{"n":"%s","sh":"%s","mat":"%s","v":%d,"sp":"%s"}',
          id, esc(a.caption), esc(a.shape), esc(a.material),
          tonumber(a.variant) or -1, esc(a.special))
        n = n + 1
      end
    end)
    if not ok then break end
  end
  parts[#parts+1] = '"tiletype":{' .. table.concat(rows, ',') .. '}'
  print('ENUMS tiletype n=' .. n .. ' range=' .. lo .. '..' .. hi)
end

-- ---- simple id -> name enums
local function dump_enum(key, enum, hi_guess)
  local lo, hi = bounds(enum, hi_guess)
  local rows, n = {}, 0
  for id = lo, hi do
    local ok, name = pcall(function() return enum[id] end)
    if ok and type(name) == 'string' then
      rows[#rows+1] = string.format('"%d":"%s"', id, esc(name))
      n = n + 1
    end
  end
  parts[#parts+1] = string.format('"%s":{%s}', key, table.concat(rows, ','))
  print('ENUMS ' .. key .. ' n=' .. n .. ' range=' .. lo .. '..' .. hi)
end

dump_enum('profession', df.profession, 200)
dump_enum('job_type', df.job_type, 400)
dump_enum('building_type', df.building_type, 100)
dump_enum('item_type', df.item_type, 200)
dump_enum('tiletype_shape', df.tiletype_shape, 64)
dump_enum('tiletype_material', df.tiletype_material, 64)
dump_enum('tiletype_special', df.tiletype_special, 64)

parts[#parts+1] = string.format('"df_version":"%s","dfhack_version":"%s"',
  esc(dfhack.getDFVersion()), esc(dfhack.getDFHackVersion()))

local f = io.open(out, 'w')
if not f then print('ENUMS ok=0 reason=cannot_open'); return end
local blob = '{' .. table.concat(parts, ',') .. '}'
f:write(blob); f:close()
print(string.format('ENUMS ok=1 bytes=%d path=%s', #blob, out))
