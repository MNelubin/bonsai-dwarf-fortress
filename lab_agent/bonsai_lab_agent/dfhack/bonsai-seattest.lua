-- Seat MANAGER on a squad-free citizen using our own assign_noble path, then add the
-- two things DF sets that our code did not: assignment.histfig2 and hf.flags.never_cull.
--
-- Run on a fort where the manager machinery demonstrably works, to separate "our
-- seating code is wrong" from "our fort is wrong". If manager_cooldown reloads to 1008
-- afterwards, the seating is acceptable to DF and the fault is fort-level.

local ent = df.global.plotinfo.main.fortress_entity
local mp
for _, p in ipairs(ent.positions.own) do
    if p.code == 'MANAGER' then mp = p end
end

local pick
for _, u in ipairs(dfhack.units.getCitizens(true)) do
    if not pick then
        local hf = df.historical_figure.find(u.hist_figure_id)
        if hf then
            local in_squad = false
            for _, l in ipairs(hf.entity_links) do
                if df.histfig_entity_link_type[l:getType()] == 'SQUAD' then
                    in_squad = true
                end
            end
            local held = dfhack.units.getNoblePositions(u) or {}
            if (not in_squad) and #held == 0 and dfhack.units.isAdult(u) then
                pick = u
            end
        end
    end
end
if not pick then print('no squad-free candidate'); return end

local hf = df.historical_figure.find(pick.hist_figure_id)
print('candidate unit', pick.id, 'hf', hf.id)

for _, a in ipairs(ent.positions.assignments) do
    if a.position_id == mp.id then
        -- Strip any POSITION link a PREVIOUS holder still carries for this assignment.
        -- Leaving it behind means two histfigs claim one seat, and DF's lookup walks
        -- links, not the assignment — so the stale one can win.
        if a.histfig ~= -1 and a.histfig ~= hf.id then
            local old = df.historical_figure.find(a.histfig)
            if old then
                for i = #old.entity_links - 1, 0, -1 do
                    local l = old.entity_links[i]
                    if df.histfig_entity_link_type[l:getType()] == 'POSITION'
                        and l.entity_id == ent.id and l.assignment_id == a.id then
                        old.entity_links:erase(i)
                        print('stripped stale link from hf', old.id)
                    end
                end
            end
        end
        a.histfig = hf.id
        a.histfig2 = hf.id
        local have = false
        for _, l in ipairs(hf.entity_links) do
            if df.histfig_entity_link_type[l:getType()] == 'POSITION'
                and l.entity_id == ent.id and l.assignment_id == a.id then
                have = true
            end
        end
        if not have then
            local link = df.histfig_entity_link_positionst:new()
            link.entity_id = ent.id
            link.assignment_id = a.id
            link.start_year = df.global.cur_year
            link.link_strength = 100
            hf.entity_links:insert('#', link)
        end
        print('seated on assignment', a.id, 'hf', a.histfig, 'hf2', a.histfig2)
    end
end
hf.flags.never_cull = true
df.global.plotinfo.nobles.manager_cooldown = 0

local codes = {}
for _, np in ipairs(dfhack.units.getNoblePositions(pick) or {}) do
    codes[#codes + 1] = np.position.code
end
print('noble now', table.concat(codes, ','))
