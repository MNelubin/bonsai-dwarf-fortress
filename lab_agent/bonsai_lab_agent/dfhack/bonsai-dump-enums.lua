-- One-time dump of the DF enums the replay viewer needs to render a recording as a
-- readable fort rather than a grid of integers. Writes JSON to /tmp/bonsai_enums.json.
--
-- Recordings store raw ids (tiletype 261, profession 102, job 51) because that keeps
-- them small and lossless; this table is what turns those back into "smooth granite
-- wall" and "Miner". It is versioned WITH the DF build - a different DF renumbers
-- these, which is exactly why regime_key already includes df_version.
local out = '/tmp/bonsai_enums.json'
local parts = {}

local function esc(s)
  s = tostring(s or '')
  s = s:gsub('\\', '\\\\'):gsub('"', '\\"'):gsub('\n', ' ')
  return s
end

-- ---- tiletypes: id -> {name, shape, material, variant, special, direction}
do
  local rows = {}
  for id, a in ipairs(df.tiletype.attrs) do
    local ok = pcall(function()
      rows[#rows+1] = string.format(
        '"%d":{"n":"%s","sh":"%s","mat":"%s","v":%d,"sp":"%s"}',
        id, esc(a.caption), esc(a.shape), esc(a.material), a.variant or -1, esc(a.special))
    end)
    if not ok then break end
  end
  parts[#parts+1] = '"tiletype":{' .. table.concat(rows, ',') .. '}'
end

-- ---- simple id -> name enums
local function dump_enum(key, enum)
  local rows = {}
  pcall(function()
    for name, id in pairs(enum) do
      if type(id) == 'number' and type(name) == 'string' then
        rows[#rows+1] = string.format('"%d":"%s"', id, esc(name))
      end
    end
  end)
  parts[#parts+1] = string.format('"%s":{%s}', key, table.concat(rows, ','))
end

dump_enum('profession', df.profession)
dump_enum('job_type', df.job_type)
dump_enum('building_type', df.building_type)
dump_enum('item_type', df.item_type)
dump_enum('tiletype_shape', df.tiletype_shape)
dump_enum('tiletype_material', df.tiletype_material)

parts[#parts+1] = string.format('"df_version":"%s","dfhack_version":"%s"',
  esc(dfhack.getDFVersion()), esc(dfhack.getDFHackVersion()))

local f = io.open(out, 'w')
if not f then print('ENUMS ok=0'); return end
f:write('{' .. table.concat(parts, ',') .. '}')
f:close()
local sz = 0
pcall(function() local g = io.open(out, 'r'); sz = #g:read('*a'); g:close() end)
print(string.format('ENUMS ok=1 bytes=%d path=%s', sz, out))
