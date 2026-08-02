-- click-text: find a target string on the rendered screen, click its centre via a
-- simulated mouse press. This is how the headless boot walks DF's main menu — v50's
-- menus are widget UI that ignores simulateInput key events, so clicking rendered text
-- is the only automation route that works.
--
-- The target comes in as a SCRIPT ARGUMENT. It used to be read from a single shared
-- click_target.txt, which made the menu phase un-parallelisable: three episodes booting
-- at once overwrote each other's target between the write and the click, and two of the
-- three died with LOADFAIL:savelist. Arguments are per-call and cannot race.
--
-- dfhack-run may split the argument on spaces, so every argument is rejoined ("Continue
-- active game" arrives as three). The file is still honoured as a fallback so an older
-- caller keeps working.
local scr = dfhack.screen
local gps = df.global.gps
local W = tonumber(gps.dimx) or 128
local H = tonumber(gps.dimy) or 64

local target = table.concat({ ... }, " ")
if #target == 0 then
    target = "Start new game in existing world"
    local f = io.open("/srv/df-bonsai/current/click_target.txt", "r")
    if f then local l = f:read("*l"); f:close(); if l and #l > 0 then target = l end end
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

local fx, fy
for y = 0, H - 1 do
    local s = rowtext(y)
    local i = string.find(s, target, 1, true)
    if i then fx = (i - 1) + math.floor(#target / 2); fy = y; break end
end
if not fx then print("NOTFOUND: " .. target); return end
print("FOUND col=" .. fx .. " row=" .. fy)

local before = table.concat(dfhack.gui.getCurFocus(true), ",")
gps.mouse_x = fx
gps.mouse_y = fy
pcall(function() gps.mouse_x_px = fx * 8 + 4 end)
pcall(function() gps.mouse_y_px = fy * 12 + 6 end)
local vs = dfhack.gui.getDFViewscreen(true)
local gui = require("gui")
pcall(function() gui.simulateInput(vs, "_MOUSE_L_DOWN") end)
pcall(function() gui.simulateInput(vs, "_MOUSE_L") end)

local after = table.concat(dfhack.gui.getCurFocus(true), ",")
print("BEFORE=" .. before)
print("AFTER=" .. after)
print("CHANGED=" .. tostring(before ~= after))
