-- Screen-grab: dump the tile ids the GAME ITSELF has composited for each screen
-- cell. This is the game's own sprite choice (variants, layers, unit art) --
-- the opposite of re-implementing its rules: we read what it drew.
-- Writes one JSON line to the given path: {win={x,y,z}, w, h, tiles=[id...], fg=[..], bg=[..]}
-- Arrays are row-major over the whole window; -1 marks an empty cell.
local out = ...
local path = (out and #out > 0) and out or '/tmp/screengrab.json'

local w, h = dfhack.screen.getWindowSize()
local tiles, fgs, bgs = {}, {}, {}
for y = 1, h do
  for x = 1, w do
    local t = dfhack.screen.readTile(x, y, false)
    local i = (y - 1) * w + x
    if t then
      tiles[i] = t.tile ~= nil and t.tile or -1
      fgs[i] = tonumber(t.fg) or -1
      bgs[i] = tonumber(t.bg) or -1
    else
      tiles[i] = -1
      fgs[i] = -1
      bgs[i] = -1
    end
  end
end

local fh = io.open(path, 'w')
fh:write(string.format(
  '{"win":[%d,%d,%d],"w":%d,"h":%d,"tiles":[%s],"fg":[%s],"bg":[%s]}',
  df.global.window_x, df.global.window_y, df.global.window_z, w, h,
  table.concat(tiles, ','), table.concat(fgs, ','), table.concat(bgs, ',')))
fh:close()
print('SCREENDUMP ok w=' .. w .. ' h=' .. h .. ' -> ' .. path)
