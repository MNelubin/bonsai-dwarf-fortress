-- Try several shapes of the same order at once and see which, if any, dispatches.
--
-- On a hand-played fort a ConstructBed order with material_category.wood and both status
-- bits set completes; on ours nothing happens with a built workshop and free logs. Rather
-- than keep testing one field per fort-run, put four variants in the list together and
-- let the fort sort them out: frequency OneTime vs Daily, workshop pinned vs not.

local w = df.global.world
local mo = w.manager_orders

local shop
for _, b in ipairs(w.buildings.all) do
    if df.building_workshopst:is_instance(b) and b.type == df.workshop_type.Carpenters then
        shop = b; break
    end
end
if not shop then print('MATRIX no carpenters workshop'); return end

-- start from a clean list so the counts afterwards are attributable
while #mo.all > 0 do
    local o = mo.all[0]
    mo.all:erase(0)
    o:delete()
end

local function make(freq, pin)
    local o = df.manager_order:new()
    o.id = mo.manager_order_next_id
    mo.manager_order_next_id = mo.manager_order_next_id + 1
    o.job_type = df.job_type.ConstructBed
    o.amount_left = 2
    o.amount_total = 2
    o.frequency = freq
    o.material_category.wood = true
    o.workshop_id = pin and shop.id or -1
    o.max_workshops = 0
    o.status.validated = true
    o.status.active = true
    mo.all:insert('#', o)
    return o
end

local variants = {
    { name = 'OneTime/unpinned', freq = 0, pin = false },
    { name = 'Daily/unpinned',   freq = 1, pin = false },
    { name = 'OneTime/pinned',   freq = 0, pin = true },
    { name = 'Daily/pinned',     freq = 1, pin = true },
}
for _, v in ipairs(variants) do
    local o = make(v.freq, v.pin)
    print(string.format('%-18s id=%d freq=%s ws=%d', v.name, o.id,
        tostring(o.frequency), o.workshop_id))
end

local beds = 0
for _, i in ipairs(w.items.all) do
    if i:getType() == df.item_type.BED then beds = beds + 1 end
end
print('MATRIX placed=' .. #mo.all, 'beds_before=' .. beds, 'shop=' .. shop.id,
    'shop_jobs=' .. #shop.jobs)
