-- click-row: click the centre of the rendered text on a given screen ROW.
--
-- click-text finds the FIRST occurrence of a string, which is wrong whenever the
-- menu shows several entries that share a label. Two of our worlds are both named
-- Thadar Thran, "The Planets of Dawning", so clicking the name always selected the
-- first and the mature region3 fortress in Kar Kodor was unreachable. The save list
-- has the same trap: "ourfort16" is a prefix of "ourfort16-lab", so clicking the
-- shorter name lands on the wrong save.
--
-- Rows come from screen-dump, which already prints "row|text", so the caller can pick
-- an exact line and click it. An optional COL overrides the computed centre.
local scr = dfhack.screen
local gps = df.global.gps
local W = tonumber(gps.dimx) or 128
local H = tonumber(gps.dimy) or 64

local args = { ... }
local row = tonumber(args[1])
local col = tonumber(args[2])
if not row or row < 0 or row >= H then
    print("BADROW: " .. tostring(args[1]))
    return
end

local function rowtext(y)
    local t = {}
    for x = 0, W - 1 do
        local ok, tl = pcall(function() return scr.readTile(x, y) end)
        local c = (ok and tl and tl.ch) or 32
        t[#t + 1] = string.char((c >= 32 and c < 127) and c or 32)
    end
    return table.concat(t)
end

local s = rowtext(row)
if not col then
    local first = string.find(s, "%S")
    local last = string.len((string.gsub(s, "%s+$", "")))
    if not first or last <= first then print("EMPTYROW: " .. row); return end
    col = math.floor((first - 1 + last) / 2)
end
print("CLICK row=" .. row .. " col=" .. col)

local before = table.concat(dfhack.gui.getCurFocus(true), ",")
gps.mouse_x = col
gps.mouse_y = row
pcall(function() gps.mouse_x_px = col * 8 + 4 end)
pcall(function() gps.mouse_y_px = row * 12 + 6 end)
local vs = dfhack.gui.getDFViewscreen(true)
local gui = require("gui")
pcall(function() gui.simulateInput(vs, "_MOUSE_L_DOWN") end)
pcall(function() gui.simulateInput(vs, "_MOUSE_L") end)

local after = table.concat(dfhack.gui.getCurFocus(true), ",")
print("BEFORE=" .. before)
print("AFTER=" .. after)
print("CHANGED=" .. tostring(before ~= after))
