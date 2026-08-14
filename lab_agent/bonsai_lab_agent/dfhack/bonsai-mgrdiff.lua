-- Dump every piece of state DF could plausibly consult when deciding whether a
-- manager work order becomes validated and active.
--
-- Written to be diffed between two forts: one where orders demonstrably validate
-- (a hand-played save) and one where they never do (our scripted embark). Guessing
-- which field matters has cost several days; a field-by-field diff does not guess.
--
-- Output is one `key = value` per line, sorted, so `diff` is meaningful. Anything
-- fort-specific that would differ harmlessly (names, ids of unrelated objects) is
-- deliberately reduced to a shape rather than printed raw.

local out = {}
local function p(k, v)
    if type(v) == 'boolean' then v = v and 1 or 0 end
    out[#out + 1] = string.format('%s = %s', k, tostring(v))
end
local function safe(k, f)
    local ok, v = pcall(f)
    p(k, ok and v or ('ERR:' .. tostring(v)))
end

local pi = df.global.plotinfo
local w = df.global.world

-- ---------------------------------------------------------------- fort identity
safe('plotinfo.civ_id', function() return pi.civ_id end)
safe('plotinfo.group_id', function() return pi.group_id end)
safe('plotinfo.race_id', function() return pi.race_id end)
safe('plotinfo.site_id', function() return pi.site_id end)
safe('plotinfo.fortress_entity.id', function() return pi.main.fortress_entity.id end)
safe('plotinfo.fortress_entity.type', function()
    return df.historical_entity_type[pi.main.fortress_entity.type]
end)
safe('plotinfo.population.n', function() return #pi.population end)
safe('units.active.n', function() return #w.units.active end)
safe('cur_year', function() return df.global.cur_year end)
safe('cur_year_tick', function() return df.global.cur_year_tick end)

-- how old is the world? the last difference we know of between the two forts
safe('world.worldgen_years', function()
    return w.world_data.world_gen_params_string and '?' or df.global.cur_year
end)
safe('world.entities.n', function() return #w.entities.all end)
safe('world.history.figures.n', function() return #w.history.figures end)
safe('world.sites.n', function() return #w.world_data.sites end)

-- ---------------------------------------------------------------- the manager seat
local ent = pi.main.fortress_entity
local mgr_pos, mgr_asg
if ent then
    for _, pos in ipairs(ent.positions.own) do
        if pos.code == 'MANAGER' then mgr_pos = pos end
    end
    for _, a in ipairs(ent.positions.assignments) do
        if mgr_pos and a.position_id == mgr_pos.id then mgr_asg = a end
    end
end

p('entity.positions.own.n', ent and #ent.positions.own or -1)
p('entity.positions.assignments.n', ent and #ent.positions.assignments or -1)
p('manager.position_found', mgr_pos and 1 or 0)

if mgr_pos then
    -- field names drift between DF builds, so read each one defensively rather than
    -- letting a single renamed field abort the whole dump
    for _, f in ipairs {'id', 'precedence', 'required_office', 'required_population',
                        'required_bedroom', 'required_boxes', 'required_dining',
                        'number', 'appointed_by', 'succession_by_position'} do
        safe('manager.pos.' .. f, function() return mgr_pos[f] end)
    end
    -- the responsibility flag is what DF's own code is most likely to match on,
    -- rather than the literal code string we happen to have searched for
    local resp = {}
    for name, v in pairs(mgr_pos.responsibilities) do
        if v == true then resp[#resp + 1] = name end
    end
    table.sort(resp)
    p('manager.pos.responsibilities', table.concat(resp, ','))
    local fl = {}
    for name, v in pairs(mgr_pos.flags) do
        if v == true then fl[#fl + 1] = name end
    end
    table.sort(fl)
    p('manager.pos.flags', table.concat(fl, ','))
end

p('manager.assignment_found', mgr_asg and 1 or 0)
if mgr_asg then
    safe('manager.asg.id', function() return mgr_asg.id end)
    safe('manager.asg.position_id', function() return mgr_asg.position_id end)
    safe('manager.asg.histfig_set', function() return mgr_asg.histfig ~= -1 end)
    safe('manager.asg.histfig2_set', function() return mgr_asg.histfig2 ~= -1 end)
    safe('manager.asg.squad_id', function() return mgr_asg.squad_id end)

    local hf = mgr_asg.histfig ~= -1 and df.historical_figure.find(mgr_asg.histfig) or nil
    p('manager.hf_found', hf and 1 or 0)
    if hf then
        safe('manager.hf.unit_id_set', function() return hf.unit_id ~= -1 end)
        safe('manager.hf.died', function() return hf.died_year ~= -1 end)
        safe('manager.hf.civ_id', function() return hf.civ_id end)
        -- the position entity link is the half of the seat that writing the
        -- assignment alone does not create; without it getNoblePositions is empty
        safe('manager.hf.entity_links', function()
            local links = {}
            for _, l in ipairs(hf.entity_links) do
                local t = df.histfig_entity_link_type[l:getType()]
                links[#links + 1] = t .. ':' .. tostring(l.entity_id)
            end
            table.sort(links)
            return table.concat(links, ',')
        end)

        local u = hf.unit_id ~= -1 and df.unit.find(hf.unit_id) or nil
        p('manager.unit_found', u and 1 or 0)
        if u then
            for _, f in ipairs {'id', 'civ_id', 'population_id'} do
                safe('manager.unit.' .. f, function() return u[f] end)
            end
            for _, f in ipairs {'dead', 'inactive', 'caged', 'chained'} do
                safe('manager.unit.flags1.' .. f, function() return u.flags1[f] end)
            end
            safe('manager.unit.is_citizen', function() return dfhack.units.isCitizen(u) end)
            safe('manager.unit.owned_buildings.n', function() return #u.owned_buildings end)
            safe('manager.unit.owned_building_types', function()
                local owned = {}
                for _, b in ipairs(u.owned_buildings) do
                    owned[#owned + 1] = df.building_type[b:getType()]
                end
                table.sort(owned)
                return table.concat(owned, ',')
            end)
            safe('manager.unit.job', function()
                return u.job.current_job and df.job_type[u.job.current_job.job_type] or 'none'
            end)
            safe('manager.unit.mood', function() return df.mood_type[u.mood] end)
        end
    end
end

safe('getNoblePositions', function()
    local names = {}
    for _, u in ipairs(w.units.active) do
        if dfhack.units.isCitizen(u) then
            local np = dfhack.units.getNoblePositions(u) or {}
            for _, n in ipairs(np) do names[#names + 1] = n.position.code end
        end
    end
    table.sort(names)
    return table.concat(names, ',')
end)

-- ---------------------------------------------------------------- the orders
local mo = w.manager_orders
safe('manager_orders.all.n', function() return #mo.all end)
safe('manager_orders.next_id', function() return mo.manager_order_next_id end)
safe('plotinfo.manager_cooldown', function() return pi.manager_cooldown end)
safe('plotinfo.manager_timer', function() return pi.manager_timer end)

local ok = pcall(function()
    for i, o in ipairs(mo.all) do
        local k = 'order[' .. i .. ']'
        for _, f in ipairs {'id', 'amount_left', 'amount_total', 'frequency',
                            'workshop_id', 'max_workshops', 'finished_year',
                            'item_type', 'item_subtype', 'mat_type', 'mat_index'} do
            safe(k .. '.' .. f, function() return o[f] end)
        end
        safe(k .. '.job', function() return df.job_type[o.job_type] end)
        safe(k .. '.validated', function() return o.status.validated end)
        safe(k .. '.active', function() return o.status.active end)
        safe(k .. '.item_conditions.n', function() return #o.item_conditions end)
        safe(k .. '.order_conditions.n', function() return #o.order_conditions end)
        safe(k .. '.items.n', function() return #o.items end)
        safe(k .. '.material_category', function()
            local f = {}
            for n, v in pairs(o.material_category) do
                if v == true then f[#f + 1] = n end
            end
            table.sort(f); return table.concat(f, ',')
        end)
    end
end)
p('order_dump_ok', ok and 1 or 0)

-- ---------------------------------------------------------------- workshops
safe('buildings.n', function() return #w.buildings.all end)
safe('workshops', function()
    local counts = {}
    for _, b in ipairs(w.buildings.all) do
        if df.building_workshopst:is_instance(b) then
            local n = df.workshop_type[b.type]
            counts[n] = (counts[n] or 0) + 1
        end
    end
    local ks = {}
    for k, v in pairs(counts) do ks[#ks + 1] = k .. 'x' .. v end
    table.sort(ks); return table.concat(ks, ',')
end)
safe('workshop.max_general_orders', function()
    for _, b in ipairs(w.buildings.all) do
        if df.building_workshopst:is_instance(b) then
            return b.profile.max_general_orders
        end
    end
    return 'no-workshop'
end)

table.sort(out)
print(table.concat(out, '\n'))
