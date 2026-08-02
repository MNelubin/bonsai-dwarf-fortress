-- bonsai-dump-geology: per-tile PALETTE ROW for the loaded save, RLE'd to one JSON line.
--
-- DF v50 draws natural rock and soil from GREYSCALE PALETTE sprites and recolours them
-- at draw time. Measured in our own atlas: 100% of the visible pixels of
-- SOIL_WALL_N_S_W_E_1 and STONE_WALL_N_S_W_E_1 are colours from row 0 of
-- data/vanilla/vanilla_descriptors_graphics/graphics/images/palettes.png, while floors,
-- grass and shrubs use none of them. Drawing the key art unswapped is why soil walls
-- came out grey instead of brown.
--
-- The row is simply the material's descriptor colour + 1: descriptors.colors has 136
-- entries whose ids (AMBER, AMETHYST, AQUA, ASH_GRAY, ...) are exactly the
-- PALETTE_COLOR names in palette_default.txt, numbered 1..136 against a palettes.png of
-- 137 rows whose row 0 is the key art. Row 0 therefore means "leave alone".
--
-- Geology is fixed at worldgen, so one dump describes every recording of a given save —
-- including recordings made before the map track carried materials. Mining changes a
-- tile's SHAPE, never its material.
--
--   dfhack-run bonsai-dump-geology <out.json> [z0] [z1]

local out_path, z0s, z1s = ...
out_path = (out_path and #out_path > 0) and out_path or '/tmp/geology.json'

local w = df.global.world
local m = w.map
local INO = w.raws.inorganics.all or w.raws.inorganics
local COLS = w.raws.descriptors.colors

-- mat_index -> palette row, memoised: the lookup walks three raw structures and the same
-- handful of layer stones repeat across millions of tiles.
local ROW = {}
local function row_of(mi)
    if mi == nil or mi < 0 then return 0 end
    local r = ROW[mi]
    if r ~= nil then return r end
    r = 0
    pcall(function()
        local raw = INO[mi]
        if raw then r = (raw.material.state_color.Solid or -1) + 1 end
    end)
    if r < 0 or r > 136 then r = 0 end
    ROW[mi] = r
    return r
end

local z0 = tonumber(z0s) or 0
local z1 = tonumber(z1s) or (m.z_count - 1)
z0 = math.max(0, z0); z1 = math.min(m.z_count - 1, z1)
local W, H = m.x_count, m.y_count

-- geo_index is a property of the region tile, not of the map tile, and resolving it costs
-- a call per lookup — cache per 16x16 block.
local function block_geo(bx, by, z)
    local ok, gi = pcall(function()
        return dfhack.maps.getRegionBiome(dfhack.maps.getTileBiomeRgn(bx * 16, by * 16, z)).geo_index
    end)
    return ok and gi or nil
end

local runs, cur, cnt, ntile = {}, nil, 0, 0
local function emit(v)
    if v == cur then cnt = cnt + 1
    else
        if cur ~= nil then runs[#runs + 1] = cur .. ',' .. cnt end
        cur, cnt = v, 1
    end
    ntile = ntile + 1
end

local nvein = 0
for z = z0, z1 do
    for y = 0, H - 1 do
        local by, iy = math.floor(y / 16), y % 16
        for bx = 0, math.floor((W - 1) / 16) do
            local blk = dfhack.maps.getTileBlock(bx * 16, by * 16, z)
            -- Veins override the layer stone. block_square_event_mineralst carries a
            -- per-row bitmask, so a tile is in the vein when its bit is set; later events
            -- win, which is how DF layers clusters over veins.
            local veins = {}
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
            local geo = blk and block_geo(bx, by, z) or nil
            for ix = 0, 15 do
                local x = bx * 16 + ix
                if x < W then
                    local v = 0
                    if blk then
                        local mi
                        for k = 1, #veins do
                            local bm, vmat = veins[k][1], veins[k][2]
                            local okb, hit = pcall(function()
                                return bit32 and bit32.band(bm.bits[iy], bit32.lshift(1, ix)) ~= 0
                                    or (bm.bits[iy] >> ix) % 2 == 1
                            end)
                            if okb and hit then mi = vmat end
                        end
                        if mi then nvein = nvein + 1 end
                        if mi == nil and geo then
                            pcall(function()
                                local gl = blk.designation[ix][iy].geolayer_index
                                mi = w.world_data.geo_biomes[geo].layers[gl].mat_index
                            end)
                        end
                        v = row_of(mi)
                    end
                    emit(v)
                end
            end
        end
    end
end
if cur ~= nil then runs[#runs + 1] = cur .. ',' .. cnt end

-- name the rows we actually used, so a reader can sanity-check without the raws
local used, names = {}, {}
for i = 1, #runs, 1 do
    local r = tonumber(runs[i]:match('^(-?%d+)'))
    if r and r > 0 and not used[r] then
        used[r] = true
        pcall(function() names[#names + 1] = '"' .. r .. '":"' .. COLS[r - 1].id .. '"' end)
    end
end

local f = io.open(out_path, 'w')
f:write(string.format(
    '{"save":"%s","origin":[0,0,%d],"dims":[%d,%d,%d],"ncolors":%d,"names":{%s},"prle":[%s]}',
    tostring(w.cur_savegame.save_dir), z0, W, H, z1 - z0 + 1, #COLS,
    table.concat(names, ','), table.concat(runs, ',')))
f:close()
print(string.format('GEOLOGY ok=1 tiles=%d runs=%d vein_tiles=%d z=%d..%d out=%s',
    ntile, #runs, nvein, z0, z1, out_path))
