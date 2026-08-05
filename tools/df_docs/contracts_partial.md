# DFHack action contracts — PARTIAL research dump

Paused mid-run on 2026-08-06. Three of seven research lanes finished before the stop;
the synthesis phase never ran, so this is raw material, not a specification.

- 54 proposed contracts across 3 lanes
- 20 adversarial reviews (skeptics were told to default to holds=false,
  so a false verdict means *unconfirmed*, not *disproven* — read the correction)

Lanes that never reported: rooms, blueprints, zones, buildings (4 of 7).

**Nothing here is verified enough to implement from.** Every `confirmed` rating below is
the proposing agent's own claim; the reviews that would have tested them are incomplete.
Re-run the workflow before trusting any of it.

---

## Lane 1 — self-rated confidence: high

### `create_zone` — confirmed
**Purpose.** Carve out a rectangular activity zone of a given kind (bedroom, office, dining hall, tomb...) — in DF v50+ this, not a piece of furniture, is what a 'room' IS.

**API.** local w,h = x2-x1+1, y2-y1+1
local ext = df.reinterpret_cast(df.building_extents_type, df.new('uint8_t', w*h))
for i=0,w*h-1 do ext[i]=1 end   -- row-major, index = ey*w+ex; 1=in zone, 0=out
local bld,err = dfhack.buildings.constructBuilding{
  type=df.building_type.Civzone, subtype=df.civzone_type[kind],
  abstract=true, pos=xyz2pos(x1,y1,z), width=w, height=h,
  fields={ assigned_unit_id=-1,
           room={x=x1,y=y1,width=w,height=h,extents=ext} } }
if bld then bld.spec_sub_flag.active = true end

**Fields.** kind: string, one of the 18 df.civzone_type names confirmed present in this build — MeetingHall, Bedroom, DiningHall, Pen, Pond, WaterSource, Dungeon, FishingArea, SandCollection, Office, Dormitory, Barracks, ArcheryRange, Dump, AnimalTraining, Tomb, PlantGathering, ClayCollection. x1,y1,x2,y2,z: int32 map tiles (x1<=x2, y1<=y2). Zone must not overlap another zone's FLOOR tiles. abstract=true is mandatory for civzones; omitting it raises. Tiles that are `hidden` should be filtered out first (quickfort's is_valid_zone_tile does exactly `not dfhack.maps.getTileFlags(pos).hidden`).

**Observable.** `#df.global.world.buildings.other.ZONE_BEDROOM` (or ZONE_OFFICE / ZONE_DINING_HALL / ZONE_TOMB / ZONE_DORMITORY / ZONE_BARRACKS / ZONE_MEETING_HALL) increments by 1; `dfhack.buildings.findCivzonesAt(pos)` returns the new zone at any covered tile; `bld.id`, `bld:getSubtype()` == the civzone_type you asked for.

**Risk.** If constructBuilding errors AFTER you allocated `extents`, the memory is freed by DFHack (documented) — but if you allocate and never call, you leak. Overlapping an existing zone's floor tiles zeroes BOTH zones' value (v53 wiki) — the agent can silently destroy an existing good room by painting on top of it. Guard: call findCivzonesAt on every tile of the proposed rect and refuse if any hit.

### `set_zone_extents` — confirmed
**Purpose.** Repaint an existing zone to a non-rectangular or resized footprint without deleting and recreating it (the way a player drags the zone paint tool).

**API.** local w,h = new_w, new_h
local ext = df.reinterpret_cast(df.building_extents_type, df.new('uint8_t', w*h))
for i=0,w*h-1 do ext[i] = mask[i] and 1 or 0 end
bld.room.x, bld.room.y = x1, y1
bld.room.width, bld.room.height = w, h
bld.room.extents = ext
bld.x1,bld.y1,bld.x2,bld.y2 = x1,y1,x1+w-1,y1+h-1
dfhack.buildings.notifyCivzoneModified(bld)

**Fields.** bld: building_civzonest. x1,y1: int32 upper-left. w,h: int32. mask: array of w*h booleans, row-major (index = ey*w+ex).

**Observable.** `dfhack.buildings.countExtentTiles(bld.room, 0)` returns the new tile count; `dfhack.buildings.containsTile(bld, x, y)` flips for tiles you added/removed.

**Risk.** Forgetting notifyCivzoneModified leaves DF's civzone<->building association map stale, so furniture inside the new area is not seen as part of the room (documented purpose of that call). Old extents array is leaked unless you df.delete it.

### `set_zone_active` — confirmed
**Purpose.** Turn a zone on or off without destroying it — the player's 'suspend zone' toggle.

**API.** bld.spec_sub_flag.active = true   -- or false

**Fields.** bld: building_civzonest. active: bool. quickfort sets this to true on EVERY zone it creates, and exposes `active=false` as a blueprint property; a zone created without it is inert.

**Observable.** bld.spec_sub_flag.active reads back; an inactive bedroom stops being usable by its owner (no sleep jobs targeting it).

**Risk.** constructBuilding does NOT set active for you. A zone library that omits this produces zones that look right in every dump and do nothing in game — exactly the class of silent no-op that already cost this project a year of dig designations.

### `rename_zone` — confirmed
**Purpose.** Give a zone a stable human/agent-readable handle so later actions can find it again across steps.

**API.** bld.name = 'noble_office_1'

**Fields.** bld: building_civzonest. name: std::string (DF-side CP437). entomb.lua guards with `if #tomb.name > 0` then falls back to `dfhack.buildings.getName(zone)`, so empty string means 'unnamed'.

**Observable.** `bld.name` reads back; `dfhack.buildings.getName(bld)` still returns the generic type name (e.g. 'Bedroom'), so the two are independent.

**Risk.** Names are not unique and not indexed — the dispatcher must keep its own name->id map, or scan the ZONE_* vectors. Do not use the name as the identity key across a save/load.

### `delete_zone` — confirmed
**Purpose.** Remove a zone the agent regrets, freeing its tiles for a better design.

**API.** dfhack.buildings.deconstruct(zone)   -- returns true if destroyed immediately

**Fields.** zone: building_civzonest. No other args. Abstract buildings are destroyed synchronously (no deconstruct job).

**Observable.** The zone disappears from `df.global.world.buildings.other.ZONE_*` and from `dfhack.buildings.findCivzonesAt(pos)`; any owner's `unit.owned_buildings` shrinks.

**Risk.** quickfort explicitly refuses to deconstruct the zone that is currently selected in the UI because it CRASHES the game (`dfhack.gui.getSelectedCivZone(true)` guard, comment: 'ensure we don't delete the currently selected zone, which causes crashes'). Headless we are unlikely to have a selection, but the dispatcher should replicate the guard.

### `assign_room_owner` — confirmed
**Purpose.** Give a specific dwarf a specific room — the thing that turns a bedroom zone into THAT dwarf's bedroom and starts the quality thoughts.

**API.** dfhack.buildings.setOwner(zone, unit)   -- always returns true

**Fields.** zone: building_civzonest (Bedroom/Office/DiningHall/Tomb are the four owner-bearing kinds; store-owned.lua iterates exactly those). unit: df.unit or nil.

**Observable.** `zone.assigned_unit_id == unit.id`; `unit.owned_buildings` contains the zone; `dfhack.buildings.getOwner(zone)` returns the unit. If the unit has a spouse and `zone:canUseSpouseRoom()`, the spouse's owned_buildings gets it too.

**Risk.** Do NOT hand-write `zone.assigned_unit_id = unit.id` alone — that is the exact desync `fix/ownership.lua` exists to repair (it un-sets and re-sets the owner through setOwner to rebuild the link). setOwner also maintains `owner_unit_cached_index`, which raw assignment does not.

### `unassign_room_owner` — confirmed
**Purpose.** Free a room from its owner (dwarf died, was promoted, or the design search wants to reshuffle).

**API.** dfhack.buildings.setOwner(zone, nil)

**Fields.** zone: building_civzonest. Passing nil means unassign; DFHack erases the zone from the old owner's and the old spouse's owned_buildings.

**Observable.** `zone.assigned_unit_id == -1`; the zone is gone from `unit.owned_buildings`.

**Risk.** Unassigning a noble's room while the demand is live re-triggers the LackBedroom/NoRooms thoughts on the next check. Sequence unassign->reassign in one dispatch batch, not across steps.

### `assign_room_to_noble_role` — confirmed
**Purpose.** Bind a room to a POSITION (mayor, manager, baron) rather than to a dwarf, so it follows whoever holds the office — the correct move when the agent does not yet know who will be elected.

**API.** local pr = require('plugins.preserve-rooms')
pr.assignToRole('MAYOR', bld)      -- bld=nil clears the binding

**Fields.** code: string, an entity_position code, case-insensitive (MONARCH, DUKE, COUNT, BARON, MAYOR, GENERAL, LIEUTENANT, CAPTAIN, SHERIFF, CAPTAIN_OF_THE_GUARD, EXPEDITION_LEADER, MANAGER, BOOKKEEPER, BROKER, CHIEF_MEDICAL_DWARF, DUNGEON_MASTER, HAMMERER, MILITIA_COMMANDER, MILITIA_CAPTAIN, OUTPOST_LIAISON, DIPLOMAT, CHAMPION, FORCED_ADMINISTRATOR, MESSENGER). bld: building_civzonest or nil. Underlying native call is `preserve_rooms_assignToRole(group_codes, bld and bld.id or -1)`.

**Observable.** `preserve_rooms_getState()` returns `stats.nobles` (count of noble rooms being managed) and `stats.reservations`; `preserve_rooms_getRoleAssignment()` on the selected zone returns the code.

**Risk.** Requires the `preserve-rooms` plugin enabled with its `track-roles` feature on; `code_lookup` is only populated on SC_MAP_LOADED, so calling this before the map is loaded prints 'Noble or administrator role not found' and silently does nothing. Promotion chains are grouped (BARON->COUNT->DUKE), so assigning to BARON may capture the duke too.

### `set_tomb_admission` — confirmed
**Purpose.** Control who may be buried in a tomb zone — the difference between a noble's private mausoleum and a communal crypt.

**API.** zone.zone_settings.tomb.flags.no_citizens = true
zone.zone_settings.tomb.flags.no_pets    = true

**Fields.** zone: building_civzonest with type == df.civzone_type.Tomb. no_citizens: bool. no_pets: bool. There is also `zone_settings.tomb.flags.whole` (quickfort's Tomb default sets `whole=1`).

**Observable.** Flags read back; a tomb with both no_citizens and no_pets set stops being picked for automatic burial assignment (that is exactly why entomb.lua sets them after a manual assignment).

**Risk.** `zone_settings` is a union keyed by zone type — writing `.tomb` on a Bedroom zone corrupts unrelated bytes. Always check `zone.type == df.civzone_type.Tomb` first. Same discipline for `.pen`, `.pond`, `.gather`, `.archery`.

### `build_furniture` — confirmed
**Purpose.** Place the item that a room type REQUIRES (bed for a bedroom, chair for an office, table for a dining hall, coffin for a tomb) plus the value-and-demand furniture nobles want (chest, cabinet, weapon rack, armor stand, statue, door).

**API.** local b, err = dfhack.buildings.constructBuilding{
  type = df.building_type.Bed, pos = xyz2pos(x,y,z),
  material = { mat_type = mt, mat_index = mi } }   -- filters auto-derived

**Fields.** type: df.building_type — Bed, Chair, Table, Coffin, Cabinet, Box, Armorstand, Weaponrack, Statue, Door, Well, Cage, Chain, WindowGlass, WindowGem (all present in buildings.lua's building_inputs table with their item_type/vector_id). pos: {x,y,z}. Optional `material={mat_type=int16, mat_index=int32}` (clears flags2.non_economic automatically), or `items={item,...}` for exact items, or `filters={job_item,...}`. Fixed-size furniture ignores width/height.

**Observable.** Returns the building; `#b.jobs > 0` means a construction job was queued (constructBuilding creates it UNCONSTRUCTED — the docs are explicit). Completion shows as the building appearing in `zone.contained_buildings` for the enclosing civzone and in `df.global.world.buildings.all`.

**Risk.** This is a QUEUED job, not an instant build: no dwarf with the right labor and no material means the room never gains the furniture and the tier never rises, with no error anywhere. The observable to score on is `contained_buildings`, never the return of this call. Set `bld.jobs[0].flags.do_now = true` (quickfort's do_now) to jump the queue.

### `set_build_material_filter` — confirmed
**Purpose.** Say 'make this bed out of gold' before placing it — material multiplier is the single biggest lever on furniture value (x1 common stone to x40 platinum, x300 adamantine).

**API.** local bp = require('plugins.buildingplan')
bp.setMaterialFilter(df.building_type.Bed, -1, -1, 0, {'GOLD','SILVER'})

**Fields.** btype: df.building_type. subtype: int16 (-1 if none). custom: int32 (-1 if none). filter_index: int32, 0-based, which input slot of the building (use `bp.get_num_filters(btype,subtype,custom)` to bound it). mats: array of material name strings as shown in the UI list. Companion: `bp.setMaterialMaskFilter(...)` for the coarse stone/metal/wood/glass masks, `bp.clearFilter(btype,subtype,custom,idx)`, `bp.resetFilters(...)`.

**Observable.** `bp.getMaterialFilter(btype,subtype,custom,idx)` reads the set back; `bp.getAvailableItems(...)` / `bp.countAvailableItems(...)` tells you whether anything in the fort satisfies it.

**Risk.** The filter is GLOBAL per (type,subtype,custom) and persists — set it for a gold statue and every subsequent statue the agent plans is also gold-only, starving the queue. The dispatcher must reset the filter after each planned placement.

### `set_build_quality_filter` — confirmed
**Purpose.** Demand a quality band for the furniture — the second value lever, and the only way to aim at a specific tier deterministically.

**API.** local bp = require('plugins.buildingplan')
bp.setQualityFilter(df.building_type.Bed, -1, -1, 0,
                    decorated and 1 or 0, min_q, max_q)

**Fields.** btype/subtype/custom/filter_index as above. decorated: int32 0 or 1. min_quality, max_quality: int32 clamped 0..6 by the shipped UI code — df.item_quality: 0 Ordinary, 1 WellCrafted, 2 FinelyCrafted, 3 Superior, 4 Exceptional, 5 Masterful, 6 Artifact. Invariant enforced by the UI: min<=max.

**Observable.** `bp.getQualityFilter(btype,subtype,custom,idx)`; the placed item's `item:getQuality()` after the job completes.

**Risk.** Quality is produced by the crafter's skill, not requested by the filter — a fort with only novices will never satisfy min_quality>=2 and the planned building sits forever. Always pair with an availability probe (`bp.countAvailableItems`) or a fallback to min_quality=0.

### `plan_building` — confirmed
**Purpose.** Register a placed-but-unbuildable building with buildingplan so it waits for materials instead of failing — the player's 'plan mode'.

**API.** local bp = require('plugins.buildingplan')
if bp.isPlannableBuilding(t, st, c) then bp.addPlannedBuilding(bld) end
bp.makeTopPriority(bld)     -- optional, jumps the queue
bp.scheduleCycle()          -- ask the plugin to match items next tick

**Fields.** bld: the building returned by constructBuilding. isPlannableBuilding(type:int32, subtype:int16, custom:int32) -> bool. Also available: `bp.isPlannedBuilding(bld)`, `bp.doCycle()` (synchronous match), `bp.getQueuePosition(bld)`, `bp.getGlobalSettings()`.

**Observable.** `bp.isPlannedBuilding(bld)` == true; `bp.getQueuePosition(bld)` returns its place; `bp.printStatus()` dumps counts.

**Risk.** quickfort guards with `buildingplan.isEnabled()` before calling — the plugin must be enabled or these are no-ops/errors. A planned building consumes no materials and produces no job until the cycle runs, so a scorer sampling immediately after dispatch sees nothing.

### `remove_building` — confirmed
**Purpose.** Tear out furniture that is dragging a room's value down or blocking a redesign.

**API.** local destroyed = dfhack.buildings.deconstruct(bld)

**Fields.** bld: any df.building. Returns true if destroyed and deallocated immediately (abstract buildings), false if a deconstruction job was queued instead (real furniture).

**Observable.** `dfhack.buildings.markedForRemoval(bld)` == true while the job is pending; the building leaves `world.buildings.all` when done.

**Risk.** For real furniture this is asynchronous — the room's value does not drop this tick. Do not treat the return value as success.

### `designate_smooth` — confirmed
**Purpose.** Mark floor and wall tiles for smoothing. Smoothing multiplies a tile's contribution by 4 (floor) or 5 (wall) versus 1 for rough — the cheapest large value gain available and a prerequisite for engraving.

**API.** local flags, occ = dfhack.maps.getTileFlags(x,y,z)
flags.smooth = 1                                   -- 1 = smooth, 2 = engrave
dfhack.maps.getTileBlock(x,y,z).flags.designated = true

**Fields.** rect: x1,y1,x2,y2,z int32. Only tiles whose `df.tiletype.attrs[tt].special ~= df.tiletype_special.SMOOTH` are worth marking (quickfort's is_smooth test). Only passable/mineable natural stone accepts it; quickfort additionally refuses when `occ.building > df.tile_building_occ.Passable`. Optional: `occ.dig_marked = true` for marker mode.

**Observable.** `select(1, dfhack.maps.getTileFlags(x,y,z)).smooth == 1` immediately; after the job runs, `df.tiletype.attrs[dfhack.maps.getTileType(x,y,z)].special == df.tiletype_special.SMOOTH`. That transition is the real observable and it is countable over the whole room.

**Risk.** Same trap the dig verb already hit: setting the tile flag without `block.flags.designated = true` produces zero jobs. Also needs a dwarf with the Stone Detailing labor; if nobody has it, the designations sit forever and the room stays at value 1/tile.

### `designate_engrave` — confirmed
**Purpose.** Mark ALREADY-SMOOTHED tiles for engraving. Engraving is additive and is where nearly all the value lives: floor bonus = material_value * 10 * old_quality_multiplier (1,2,3,4,5,12; 120 for artifact), so one masterwork engraving on ordinary stone adds 120 against a smoothed-floor base of 4.

**API.** local flags = dfhack.maps.getTileFlags(x,y,z)
flags.smooth = 2
dfhack.maps.getTileBlock(x,y,z).flags.designated = true

**Fields.** Identical arg schema to designate_smooth. HARD PRECONDITION: quickfort's do_engrave bails unless `df.tiletype.attrs[tt].special == df.tiletype_special.SMOOTH` already. So engraving is strictly a second pass after smoothing completes — this makes it a two-step plan, not one action.

**Observable.** A new entry appears in `df.global.world.event.engravings` whose `.pos` matches the tile and whose `.flags.floor` is true for floors, false for walls (fix/engravings.lua uses exactly this pair to validate). Count of engravings inside the room's extents is the fitness input.

**Risk.** Wall engravings only credit the room that contains BOTH the wall and the tile the engraver stood on, and a wall can only be engraved from one side — so a shared wall pays exactly one of the two rooms, and Lua cannot tell you which without inspecting the engraving's own record. Engraving quality is the engraver's skill roll, not a choice; a novice-only fort caps the payoff at x1.

### `set_designation_priority` — confirmed
**Purpose.** Order the fort's dig/smooth/engrave queue so the noble's room gets finished before decorative work — the player's 1-7 priority setting.

**API.** local bes = dfhack.maps.getTileBlock(pos).block_events
local pbse
for _,v in ipairs(bes) do
  if v:getType() == df.block_square_event_type.designation_priority then pbse=v end
end
if not pbse then
  pbse = bes:insert('#', {new=df.block_square_event_designation_priorityst})
end
pbse.priority[pos.x % 16][pos.y % 16] = priority * 1000

**Fields.** pos: {x,y,z}. priority: int, 1..7, DEFAULT 4. The stored value is priority*1000 (quickfort multiplies; it also clamps out-of-range to [1,7] and counts the clamps as stats).

**Observable.** `pbse.priority[x%16][y%16]` reads back as priority*1000; jobs for higher-priority tiles are claimed first.

**Risk.** The array is per 16x16 block, so a room straddling a block boundary needs the event created in each block. Setting priority on a tile with no designation is meaningless (quickfort resets it to 4 whenever it clears a designation).

### `build_construction` — confirmed
**Purpose.** Lay a constructed floor or wall. Constructed surfaces beat smoothed natural ones — 7x material value for floors and 9x for walls versus 4x/5x — and in v50+ they can be engraved too, which is the highest-value tile a design search can specify.

**API.** local ok = dfhack.constructions.designateNew(
  xyz2pos(x,y,z), df.construction_type.Floor,
  df.item_type.BLOCKS, mat_index)

**Fields.** pos: {x,y,z}. type: df.construction_type (Floor, Wall, Ramp, UpStair, DownStair, UpDownStair, Fortification). item_type: df.item_type (BLOCKS is the efficient choice — a block is base value 5 and one stone yields 4 blocks). mat_index: int32 material index. Returns true, or false if obstructed. Removal: `dfhack.constructions.designateRemove(pos)` -> true, was_only_planned.

**Observable.** A planned construction is technically a building (documented), so it appears in `world.buildings.all`; on completion the tiletype material becomes `df.tiletype_material.CONSTRUCTION`.

**Risk.** Constructions consume real items and take jobs — a design that specifies 200 platinum wall blocks is unbuildable and will look identical in the plan to one that is buildable. The offline search must be cost-constrained against `bp.countAvailableItems` or the fort's stone stock, or it will emit fantasy blueprints.

### `read_room_value` — inferred
**Purpose.** Compute the room's numeric value — the fitness function an offline design search optimises. There is NO DFHack getter for this; it must be recomputed from tiles plus contained furniture.

**API.** local tm = require('tile-material')
local FLOOR = {rough=1, smooth=4, constructed=7}
local WALL  = {rough=1, smooth=5, constructed=9}
local ENGQ  = {[0]=1,[1]=2,[2]=3,[3]=4,[4]=5,[5]=12,[6]=120} -- OLD multipliers
local function room_value(zone)
  local v = 0
  for y=zone.y1,zone.y2 do for x=zone.x1,zone.x2 do
    if dfhack.buildings.containsTile(zone,x,y) then
      local tt = dfhack.maps.getTileType(x,y,zone.z)
      local a  = df.tiletype.attrs[tt]
      local mi = tm.GetTileMat(x,y,zone.z)
      local mv = (mi and mi.material and mi.material.material_value) or 1
      local con = (a.material == df.tiletype_material.CONSTRUCTION)
      local sm  = (a.special  == df.tiletype_special.SMOOTH)
      local tbl = (a.shape == df.tiletype_shape.WALL) and WALL or FLOOR
      v = v + mv * (con and tbl.constructed or (sm and tbl.smooth or tbl.rough))
    end
  end end
  for _,e in ipairs(df.global.world.event.engravings) do
    if e.pos.z==zone.z and dfhack.buildings.containsTile(zone,e.pos.x,e.pos.y) then
      local mi = tm.GetTileMat(e.pos.x,e.pos.y,zone.z)
      local mv = (mi and mi.material and mi.material.material_value) or 1
      v = v + mv * 10 * (ENGQ[e.quality] or 1)
    end
  end
  for _,b in ipairs(zone.contained_buildings) do
    for _,ci in ipairs(b.contained_items) do
      if ci.item.flags.in_building then
        v = v + dfhack.items.getValue(ci.item)
      end
    end
  end
  return v
end

**Fields.** zone: building_civzonest. Returns int. Confirmed primitives: `dfhack.items.getValue(item[,caravan_state])`, `require('tile-material').GetTileMat(x,y,z)` (returns a matinfo; `.material.material_value` is the raws' MATERIAL_VALUE), `df.global.world.event.engravings` with `.pos` and `.flags.floor`, `zone.contained_buildings`, `building.contained_items[].item` with `.flags.in_building` marking the furniture item itself (the idiom store-owned.lua uses). The multiplier constants come from the wiki's v53.15 Zone article, not from this build.

**Observable.** Cross-validate ONCE against the game: build a room, read the tier name DF itself shows, and check the computed number falls in that tier's band. After that the computed number is self-consistent and usable offline with no game running at all — which is the whole point for a design search.

**Risk.** Three corrections the naive sum gets wrong: (1) zones sharing FLOOR tiles are penalised (v53 wiki: value drops to zero; the older DF2014 article says -75%) — the two sources disagree, so treat overlap as forbidden rather than modelled; (2) tiles whose material matches the OWNER's preferences are worth double, so 'a level 3 office' is not owner-independent — read `unit.status.current_soul.preferences`; (3) `engraving.quality` is an inferred field name — verify it before trusting the engraving term.

### `read_room_tier` — confirmed
**Purpose.** Turn the raw value into the named tier a player talks about ('a level 3 office'), which is what the owner actually wants to name designs by.

**API.** local MIN = {1, 100, 250, 500, 1000, 1500, 2500, 10000}
local NAME = {
  office  = {'Meager Office','Modest Office','Office','Decent Office','Splendid Office','Throne Room','Opulent Throne Room','Royal Throne Room'},
  bedroom = {'Meager Quarters','Modest Quarters','Quarters','Decent Quarters','Fine Quarters','Great Bedroom','Grand Bedroom','Royal Bedroom'},
  dining  = {'Meager Dining Room','Modest Dining Room','Dining Room','Decent Dining Room','Fine Dining Room','Great Dining Room','Grand Dining Room','Royal Dining Room'},
  tomb    = {'Grave',"Servant's Burial Chamber",'Burial Chamber','Tomb','Fine Tomb','Mausoleum','Grand Mausoleum','Royal Mausoleum'} }
local function tier(v) local t=0 for i,m in ipairs(MIN) do if v>=m then t=i end end return t end

**Fields.** value: int. kind: 'office'|'bedroom'|'dining'|'tomb'. Returns tier 1..8 (0 = below Meager) and the name. The eight thresholds are CONFIRMED three ways on this build: the MOUNTAIN entity raws use exactly {1,100,250,500,1500,2500,10000} as REQUIRED_* values, `strings dwarfort` contains the tier names, and libdfhack.so carries the full 8x4 name table in the order [office, bedroom, dining, tomb] per level.

**Observable.** Self-consistent by construction. `df.dfhack_room_quality_level` IS a registered enum type in this build and `min_value` is present as an enum-attr string, so `df.dfhack_room_quality_level.attrs[i].min_value` is likely readable at runtime — one live probe would let you drop the hardcoded table.

**Risk.** Sources disagree on whether tier 1 starts at 0 or 1 (the v53 Zone wiki table says 0, the raws' lowest REQUIRED_* is 1). Use >=1 so an empty zone scores tier 0 and the agent can tell 'nothing' from 'meager'.

### `read_noble_room_requirements` — confirmed
**Purpose.** Answer 'what does this dwarf's office have to be worth' from the game's own data instead of a hardcoded table — the requirements really are documented, in the raws AND in memory.

**API.** for _,np in ipairs(dfhack.units.getNoblePositions(unit) or {}) do
  local p = np.position
  print(p.code, p.required_office, p.required_bedroom,
        p.required_dining, p.required_tomb,
        p.required_boxes, p.required_cabinets,
        p.required_racks, p.required_stands,
        p.mandate_max, p.demand_max)
end

**Fields.** `dfhack.units.getNoblePositions(unit or histfig)` returns a list of {entity, assignment, position} or nil (documented API). entity_position fields confirmed by preserve-rooms.lua and sort.lua: `code` (string), `id`, `replaced_by`, `required_office/bedroom/dining/tomb` (int32 = the room VALUE threshold, not a tier index), `required_boxes/cabinets/racks/stands` (int32 counts), `mandate_max`, `demand_max`, `flags.ELECTED`. To enumerate all positions without a holder: `df.historical_entity.find(df.global.plotinfo.civ_id).positions.own` and the same for `plotinfo.group_id`.

**Observable.** This build's vanilla MOUNTAIN entity, verbatim (office/bedroom/dining/tomb -> tier): MONARCH 10000/10000/10000/10000 (T8) + 10 boxes 5 cabinets 5 racks 5 stands; DUKE 2500 x4 (T7) + 5/3/3/3; COUNT 1500 x4 (T6) + 3/2/2/2; DIPLOMAT and OUTPOST_LIAISON 1500/1500/1500/- (T6) + 3/2/2/2; BARON 500 x4 (T4) + 2/1/1/1; MAYOR 500/500/500/- (T4) + 2/1/1/1; GENERAL office 500 (T4), bedroom+dining 250 (T3), tomb 1 (T1) + 2/1/3/3; CAPTAIN_OF_THE_GUARD 250/250/250/- (T3) + 1/1/1/1; DUNGEON_MASTER 250/250/250/- (T3) + 1/1/1/1; SHERIFF 100/100/100/- (T2) + 1/1/1/1; LIEUTENANT 100/100/100/- (T2) + 1/1/2/2; CAPTAIN 1/1/1/- (T1) + 1/1/1/1; MANAGER office 1 (T1); BOOKKEEPER office 1 (T1). EXPEDITION_LEADER, BROKER, CHIEF_MEDICAL_DWARF, MILITIA_COMMANDER, MILITIA_CAPTAIN, HAMMERER, CHAMPION, MESSENGER, FORCED_ADMINISTRATOR: no room requirement at all. For a 7-dwarf embark the only live demands are MANAGER and BOOKKEEPER, each needing an office worth >=1 — i.e. a chair in any zone. MAYOR (T4, value 500) only appears at population 20.

**Risk.** required_* is a VALUE, not a tier index — the wiki's Noble table prints tier numbers (1..8) and it is easy to compare a value against a tier and be wrong by a factor of 1000. Also these are per-entity: a modded or non-MOUNTAIN civ has different numbers, so read them, do not bake them.

### `read_room_thoughts` — confirmed
**Purpose.** Observe whether the fort's rooms are actually landing — the per-dwarf emotional signal that a room is missing, or good, or resented. This is the closest thing to a ground-truth reward for room quality.

**API.** for _,e in ipairs(unit.status.current_soul.personality.emotions) do
  local t = df.unit_thought_type[e.thought]
  -- room-related: LackBedroom, BedroomQuality, OfficeQuality, TombQuality,
  -- TombLack, NoRooms, MeetingInBedroom, MeetingInDiningRoom,
  -- SleptFloor, SleptMud, SleptGrass, SleptRoughFloor, SleptRocks,
  -- SleptIce, SleptDirt, SleptDriftwood, Evicted
end

**Fields.** unit: df.unit. Each emotion carries `thought` (df.unit_thought_type), and the usual severity/age fields. The listed enum item names are CONFIRMED present in this build's structures (they appear contiguously in libdfhack.so's unit_thought_type name table). Matching DF display strings also present in the binary: 'after sleeping without a proper room', 'being without a proper dining room', 'after sleeing in a [quality] bedroom' (DF's own typo), 'conducted meeting in a [quality] room', "by a lesser's pretentious [room] arrangements".

**Observable.** Count of LackBedroom + NoRooms + SleptFloor/SleptRoughFloor across citizens should fall to zero once every dwarf has an owned bedroom zone with a bed; BedroomQuality/OfficeQuality/TombQuality appearing at all means the room cleared a tier the dwarf noticed.

**Risk.** Thoughts are lagging and stochastic — a dwarf must actually sleep in the room before BedroomQuality fires, so at short horizons this observable stays empty even for a perfect design. Use it as a long-horizon confirmation, not as the search's fitness. `TombLack` fires annually for a noble promised an unbuilt tomb.

### `list_rooms` — confirmed
**Purpose.** Enumerate the fort's rooms with their kind, owner, footprint and furniture — the state the agent needs before it can decide what to build next.

**API.** local other = df.global.world.buildings.other
for _,vec in ipairs({other.ZONE_BEDROOM, other.ZONE_OFFICE,
                     other.ZONE_DINING_HALL, other.ZONE_TOMB,
                     other.ZONE_DORMITORY, other.ZONE_BARRACKS,
                     other.ZONE_MEETING_HALL}) do
  for _,z in ipairs(vec) do
    local u = dfhack.buildings.getOwner(z)
    print(z.id, df.civzone_type[z:getSubtype()],
          (#z.name>0 and z.name or dfhack.buildings.getName(z)),
          z.x1, z.y1, z.x2, z.y2, z.z,
          dfhack.buildings.countExtentTiles(z.room, 0),
          z.spec_sub_flag.active, z.assigned_unit_id,
          #z.contained_buildings)
  end
end

**Fields.** No args. Per row: id int32, kind string, name string, bbox int32 x6, tiles int, active bool, assigned_unit_id int32 (-1 = none), furniture count. `z.centerx/centery/z` are also available (store-owned.lua uses them). Reverse lookups: `dfhack.buildings.findCivzonesAt(pos)` (tile -> zones), `unit.owned_buildings` (dwarf -> zones), `building.relations` (furniture -> enclosing civzones).

**Observable.** Row count matches the number of zones created; each furniture item the agent built shows up in exactly one zone's contained_buildings once its job completes.

**Risk.** The ZONE_* 'other' vectors are per-type, so a zone appears in exactly one of them — iterating only ZONE_BEDROOM misses offices. There is no single 'all civzones' vector short of scanning `world.buildings.all` and type-testing with `df.building_civzonest:is_instance(b)`.

**Lane notes.** THE OWNER IS RIGHT, WITH ONE IMPORTANT EXCEPTION. The tiers and the noble thresholds are genuinely documented and machine-readable on this build. What is NOT available is a way to ask the game for a room's number — that has to be recomputed. So a library of named designs is buildable, but its fitness function is ours, not DF's, and must be calibrated once against the game.

DEAD ENDS (do not build on these):
1. `dfhack.buildings.getRoomDescription(bld[,unit])` is documented in the shipped Lua API doc (hack/docs/docs/dev/Lua API.txt:2443) and the symbol IS exported from libdfhack.so — but upstream the entire body is commented out behind `/* TODO: understand how this changes for v50` and it returns "". Its `room_quality_names` table only ever had entries for Bed/Table/Chair/Coffin, so it never handled civzones anyway. Treat as returning empty string; if you want certainty, one live call is the cheapest possible probe.
2. `building::getRoomValue(unit)` — the DF vmethod that would give the number — is NOT registered in this build's Lua bindings. `strings libdfhack.so | grep -x getRoomValue` returns 0 hits, while sibling vmethods that ARE exposed (`canUseSpouseRoom`, `uncategorize`, `getSubtype`, `owner_unit_cached_index`) all return 1. There is no numeric room value anywhere in the exposed surface: `room_value` matches nothing.
3. `building.is_room` no longer exists — no such string in libdfhack.so. Anything keyed on it is pre-v50.
4. `hack/scripts/gui/room-list.lua` is stale and will not run on this build: it reads `building.is_room`, `df.global.ui_building_in_assign`, `df.global.ui_building_assign_units` and a `dwarfmode/QueryBuilding/...` focus path, all of which are pre-v50. It is still useful as documentation of the OLD furniture-defined-room model — which is exactly what makes it misleading. Do not copy from it.
5. RemoteFortressReader is not needed for any of this; everything above is plain in-process Lua.

VERSION QUIRK THAT REFRAMES THE WHOLE LANE. In v50+ a room is an ACTIVITY ZONE (`df.building_civzonest`), not a bed with an extent. The wiki's `Room` page for v53.15 is literally an "obsolete feature" stub. This is why "create a zone" and "assign a room to a dwarf" are genuinely two actions with two different APIs, and why furniture is a *contributor* to a zone rather than the thing that defines it. The furniture still matters — required item per type: Office needs a chair, Bedroom a bed, DiningHall a table, Tomb a coffin, Dormitory multiple beds, Barracks an armor stand/weapon rack — but the zone comes first.

THE VALUE MODEL (wiki-sourced for v53.15, not read from this build's code — treat the constants as inferred until calibrated):
  value = SUM over tiles of (material_value * surface_multiplier)
        + SUM over engravings of (material_value * 10 * old_quality_multiplier)
        + SUM over furniture of item value
  surface multipliers: floor rough 1 / smoothed 4 / constructed 7; wall rough 1 / smoothed 5 / constructed 9.
  old_quality_multiplier (engravings only): 1, 2, 3, 4, 5, 12, artifact 120.
  ITEM quality in v50 was NERFED to multiplier + flat bonus: x1.1+3, x1.2+6, x1.33+10, x1.5+15, x2.0+30, artifact x20+300 — which is why furniture is now a weak lever and floors/engravings are the strong one. Engravings still use the OLD multipliers. That asymmetry is the single most important fact for a design search: a masterwork engraving on plain stone adds 120; a masterwork bed adds far less than it used to.
  material_value comes from the raws' MATERIAL_VALUE: common stone 1, limestone/marble 2, obsidian 3, galena 5, iron ores 8, silver ores 10, native gold 30, platinum/aluminum 40, adamantine 250-300; gems 2-60; wood 1.
  Two corrections the naive sum misses: zones sharing FLOOR tiles are penalised (v53 page says value drops to zero, the older DF2014 page says -75% — the sources disagree, so forbid overlap rather than model it); and tiles whose material matches the OWNER's preferences count DOUBLE, tile and engraving alike. That second one means a design cannot be certified "level 3" independently of who lives in it.

THE TIER TABLE IS TRIPLE-CONFIRMED ON THIS BUILD. Thresholds {1, 100, 250, 500, 1000, 1500, 2500, 10000} appear as REQUIRED_* values in /srv/df-bonsai/current/data/vanilla/vanilla_entities/objects/entity_default.txt; the tier names appear in `strings dwarfort` (Royal Bedroom, Grand Mausoleum, Opulent Throne Room, ...); and libdfhack.so carries the complete 8x4 name table in [office, bedroom, dining, tomb] order. `df.dfhack_room_quality_level` is a registered enum type on this build and `min_value` exists as an enum-attr string, so `df.dfhack_room_quality_level.attrs[i].min_value` is probably readable directly — worth one live probe to replace the hardcoded table.

WHAT UNMET DEMANDS ACTUALLY DO. Not a work stoppage. They produce: unhappy thoughts (LackBedroom, NoRooms, TombLack, and the quality thoughts), stress; nobles with `mandate_max > 0` or `demand_max > 0` issue mandates and demands and can have dwarves punished for oath-breaking if a justice system exists; and a jealousy thought ("by a lesser's pretentious [room] arrangements") if a lesser dwarf has a better room — which the noble does not need to SEE to resent. `unit.demands` is a real vector on the unit struct and `df.unit_demand` is a registered type, but I did not confirm its field schema.

SERIALISABLE FORMATS THAT ALREADY EXIST — PREFER THESE OVER HAND-ROLLING:
- quickfort `zone` blueprint mode is a complete, tested, text schema for zone creation: single-letter keys b=Bedroom, o=Office, h=Dining Hall, T=Tomb, D=Dormitory, B=Barracks, m=Meeting Area, plus properties `name=`, `active=false`, `assigned_unit=<POSITION_CODE>`, `location=tavern|hospital|guildhall|library|temple`, `allow=visitors|residents|citizens|members`, and per-type props (`pets=`, `citizens=` for tombs). Implementation: /srv/df-bonsai/current/hack/scripts/internal/quickfort/zone.lua. Its `create_zone()` is the exact call sequence for building a zone correctly, extents allocation included.
- buildingplan's filters are the serialisable "level 3 office" material/quality spec: setMaterialFilter(type, subtype, custom, filter_index, {mat names}) and setQualityFilter(type, subtype, custom, filter_index, decorated 0|1, min_quality 0-6, max_quality 0-6).
- quickfort `build` mode covers the furniture placement half and already integrates with buildingplan (scripts/internal/quickfort/build.lua:1307).
A room-design library should almost certainly be authored as a quickfort zone blueprint + a build blueprint + a buildingplan filter set, rather than as bespoke Lua.

CALIBRATION THAT STILL NEEDS DOING BEFORE ANY DESIGN SEARCH IS TRUSTED (all cheap, all one live episode): (a) confirm getRoomDescription really returns ""; (b) dump `df.dfhack_room_quality_level.attrs` to replace the hardcoded thresholds; (c) confirm `engraving.quality` is the right field name; (d) build one known room, compare our computed value against the tier DF itself reports, and record the residual. Without (d) the fitness function is a plausible model of DF, not a measurement of it — and this project has already been bitten twice by reporting statistics instead of looking at the thing.

---

## Lane 2 — self-rated confidence: high

### `observe_positions` — confirmed
**Purpose.** Read the fortress's full noble/administrative roster — which positions exist, who holds each, and whether each holder's room requirements are met — so the policy can see that MANAGER is vacant.

**API.** Read-only. Fort entity is the site government: `local ent = df.global.plotinfo.main.fortress_entity` (shipped code also reaches it as `df.historical_entity.find(df.global.plotinfo.group_id)`; `plotinfo.civ_id` is the *civ*, a different entity that owns MONARCH/OUTPOST_LIAISON/BARON).

```lua
local ent = df.global.plotinfo.main.fortress_entity
local byid = {}
for i, p in ipairs(ent.positions.own) do byid[p.id] = {p = p, idx = i} end
for i, a in ipairs(ent.positions.assignments) do
  local e = byid[a.position_id]
  if e then
    local p = e.p
    print(string.format('POS %s id=%d asg=%d aidx=%d hf=%d hf2=%d sq=%d req_office=%d req_bed=%d req_dine=%d req_tomb=%d pop=%d prec=%d elected=%s',
      p.code, p.id, a.id, i, a.histfig, a.histfig2, a.squad_id,
      p.required_office, p.required_bedroom, p.required_dining, p.required_tomb,
      p.requires_population, p.precedence, tostring(p.flags.ELECTED)))
  end
end
-- the exact check DFHack itself uses for "is there a manager":
print('has_manager', #ent.assignments_by_type.MANAGE_PRODUCTION > 0)
print('has_bookkeeper', #ent.assignments_by_type.ACCOUNTING > 0)
print('mgr_cooldown', df.global.plotinfo.nobles.manager_cooldown,
      'bk_cooldown', df.global.plotinfo.nobles.bookkeeper_cooldown)
```
Also available and cheaper for a single lookup: `dfhack.units.getUnitByNobleRole('MANAGER')` / `dfhack.units.getUnitsByNobleRole('MANAGER')` (exported C++ symbols confirmed in libdfhack.so), and `dfhack.units.getNoblePositions(unit_or_histfig)` which returns a list of `{entity=, position=, assignment=}`.

**Fields.** No arguments. Emitted per position: `code` (string, e.g. MANAGER), `position_id` (int32, entity-local — NOT global), `assignment_id` (int32), `assignment_idx` (int, index into `positions.assignments`, needed later for entity links), `histfig`/`histfig2` (int32, -1 = vacant), `squad_id` (int32, -1 = none), `required_office`/`required_bedroom`/`required_dining`/`required_tomb` (int32 room-value thresholds; 0 = not required), `requires_population` (int16), `precedence` (int32), `flags.ELECTED` (bool).

**Observable.** On our pinned save this must print `POS EXPEDITION_LEADER ... hf=<id>` and `POS MANAGER ... hf=-1`, and `has_manager false`. After a successful assign_position it prints `has_manager true` and `dfhack.units.getUnitByNobleRole('MANAGER')` returns a unit.

**Risk.** `position_id` is entity-local and resolved via find-by-id against *that entity's* `positions.own` — never treat it as a global id or index. `assignments_by_type` is a static array indexed by `entity_position_responsibility`; the enum has grown well past the 25 entries older df-structures declared, so index it by NAME (`.MANAGE_PRODUCTION`) and never by a hardcoded integer. Wrap in pcall: `positions.assignments` can contain entries whose `position_id` resolves to nothing.

### `assign_position` — inferred
**Purpose.** Appoint a named dwarf to a noble/administrative position (MANAGER, BOOKKEEPER, BROKER, CHIEF_MEDICAL_DWARF, SHERIFF, MILITIA_COMMANDER, HAMMERER, MESSENGER) — the single action that unblocks the entire work-order pipeline.

**API.** There is NO DFHack API for this. The exported `DFHack::Units::` symbols are only `getNoblePositions`, `getUnitByNobleRole`, `getUnitsByNobleRole` — all getters. You must write the structures. The shipped precedent is `/srv/df-bonsai/current/hack/scripts/make-monarch.lua` (which is stale — see risk); the modern, maintained mirror-image is `unassignMayor()` in `/srv/df-bonsai/current/hack/scripts/internal/emigration/unit-link-utils.lua`.

```lua
-- assign_position(position_code, unit_id)
local ent  = df.global.plotinfo.main.fortress_entity
local unit = df.unit.find(unit_id)
local hf   = df.historical_figure.find(unit.hist_figure_id)
local pos, pidx
for i, p in ipairs(ent.positions.own) do
  if p.code == position_code then pos, pidx = p, i; break end
end
if not (pos and hf) then return 'no-such-position' end

-- reuse the vacant slot if the game already made one; NUMBER:AS_NEEDED
-- positions (MILITIA_CAPTAIN, MESSENGER) may have none yet.
local asg, aidx
for i, a in ipairs(ent.positions.assignments) do
  if a.position_id == pos.id and a.histfig == -1 then asg, aidx = a, i; break end
end
if not asg then
  asg = df.entity_position_assignment:new()
  asg.id = ent.positions.next_assignment_id
  ent.positions.next_assignment_id = asg.id + 1
  asg.position_id = pos.id
  asg.position_vector_idx = pidx
  asg.histfig, asg.histfig2, asg.squad_id = -1, -1, -1
  ent.positions.assignments:insert('#', asg)
  aidx = #ent.positions.assignments - 1
end

asg.histfig  = hf.id   -- current holder
asg.histfig2 = hf.id   -- "last holder"; set on assign, left stale on vacate

hf.entity_links:insert('#', { new = df.histfig_entity_link_positionst,
  entity_id = ent.id, assignment_id = asg.id, assignment_vector_idx = aidx,
  link_strength = 100, start_year = df.global.cur_year })

-- the index DFHack's own has_manager() reads; DF will not see the holder without it
for r, on in ipairs(pos.responsibilities) do
  if on then ent.assignments_by_type[r]:insert('#', asg) end
end

local eid = df.global.hist_event_next_id
df.global.hist_event_next_id = eid + 1
df.global.world.history.events:insert('#', { new = df.history_event_add_hf_entity_linkst,
  year = df.global.cur_year, seconds = df.global.cur_year_tick, id = eid,
  civ = ent.id, histfig = hf.id,
  link_type = df.histfig_entity_link_type.POSITION, position_id = pos.id })
```

**Fields.** `position_code` (string, uppercase raw token). Site-government positions on this build's MOUNTAIN entity, i.e. the ones a fortress player can hold: EXPEDITION_LEADER, MAYOR, MANAGER, CHIEF_MEDICAL_DWARF, BROKER, BOOKKEEPER, SHERIFF, CAPTAIN_OF_THE_GUARD, MILITIA_COMMANDER, MILITIA_CAPTAIN, HAMMERER, DUNGEON_MASTER, CHAMPION, MESSENGER. Player-appointable while only an EXPEDITION_LEADER exists (raws `[APPOINTED_BY:EXPEDITION_LEADER]`): MANAGER, CHIEF_MEDICAL_DWARF, BROKER, BOOKKEEPER, SHERIFF, MILITIA_COMMANDER, HAMMERER, MESSENGER, CAPTAIN_OF_THE_GUARD. `unit_id` (int32, a live citizen; validate with `dfhack.units.isCitizen`). Optional `allow_replace` (bool, default false) — if true, vacate the current holder first instead of failing.

**Observable.** Three independent reads, all cheap: (1) `#df.global.plotinfo.main.fortress_entity.assignments_by_type.MANAGE_PRODUCTION > 0` flips false→true — this is literally the predicate DFHack's shipped `gui/extended-status.lua:38` uses; (2) `dfhack.units.getUnitByNobleRole('MANAGER').id == unit_id`; (3) `dfhack.units.getNoblePositions(unit)` now contains an entry whose `.position.code == 'MANAGER'`. Downstream, `df.global.plotinfo.nobles.manager_cooldown` starts moving in 0..1008 and queued orders acquire `status.validated`.

**Risk.** (a) `make-monarch.lua` is a stale template — it sets only `histfig`, never `histfig2`, never touches `assignments_by_type`, and emits no history event; DFHack issue #2671 records that it needs updating for the newer `position_vector_idx` / `assignment_vector_idx` fields. Copy the snippet above, not that script. (b) Assigning a position that carries `[SQUAD:...]` (MILITIA_COMMANDER, MILITIA_CAPTAIN, CAPTAIN_OF_THE_GUARD) without also calling `dfhack.military.makeSquad(asg.id)` leaves `squad_id == -1` and a half-formed noble. (c) Do not attempt MAYOR (ELECTED, pop 50) or BARON/COUNT/DUKE (APPOINTED_BY:MONARCH) — forging those diverges from the human action surface and risks a save the game re-derives inconsistently. (d) Guard against double-assign: check `a.histfig == -1` and that the unit does not already hold the position, or you will insert duplicate entity_links and duplicate `assignments_by_type` entries.

### `vacate_position` — inferred
**Purpose.** Remove the current holder from a position — needed to replace a bad appointee (e.g. a manager who died or joined the military) without leaving a corrupt half-link.

**API.** Mirror the shipped `unassignMayor()` in `/srv/df-bonsai/current/hack/scripts/internal/emigration/unit-link-utils.lua` — that is maintained DFHack code for exactly this operation.

```lua
-- vacate_position(position_code)
local ent = df.global.plotinfo.main.fortress_entity
local pos, asg, aidx
for _, p in ipairs(ent.positions.own) do if p.code == position_code then pos = p end end
for i, a in ipairs(ent.positions.assignments) do
  if pos and a.position_id == pos.id and a.histfig ~= -1 then asg, aidx = a, i; break end
end
if not asg then return 'already-vacant' end
local hf = df.historical_figure.find(asg.histfig)
asg.histfig = -1                    -- histfig2 is deliberately LEFT as the last holder

local start_year = -1
for k, v in ipairs(hf.entity_links) do
  if v.entity_id == ent.id and df.histfig_entity_link_positionst:is_instance(v)
     and v.assignment_id == asg.id then
    start_year = v.start_year; hf.entity_links:erase(k); v:delete(); break
  end
end
hf.entity_links:insert('#', { new = df.histfig_entity_link_former_positionst,
  assignment_id = asg.id, start_year = start_year, entity_id = ent.id,
  end_year = df.global.cur_year, link_strength = 100 })

for r, on in ipairs(pos.responsibilities) do
  if on then
    local v = ent.assignments_by_type[r]
    for i = #v - 1, 0, -1 do if v[i].id == asg.id then v:erase(i) end end
  end
end

local eid = df.global.hist_event_next_id
df.global.hist_event_next_id = eid + 1
df.global.world.history.events:insert('#', { new = df.history_event_remove_hf_entity_linkst,
  year = df.global.cur_year, seconds = df.global.cur_year_tick, id = eid,
  civ = ent.id, histfig = hf.id,
  link_type = df.histfig_entity_link_type.POSITION, position_id = pos.id })
```

**Fields.** `position_code` (string, same allow-list as assign_position). No unit argument — a position has at most `entity_position.number` holders and the action targets the position, not the dwarf.

**Observable.** `assignment.histfig == -1`; `dfhack.units.getUnitByNobleRole(code)` returns nil; `#ent.assignments_by_type.<RESP> == 0`; the ex-holder's `hf.entity_links` now carries a `histfig_entity_link_former_positionst` with `end_year == df.global.cur_year` and no `histfig_entity_link_positionst` for that assignment.

**Risk.** `histfig2` must NOT be reset to -1 — the shipped code leaves it, and it is the game's "last holder" record. Erasing the wrong entity_link (there can be several, for the civ and the site government) silently detaches the dwarf from the fortress. Vacating the EXPEDITION_LEADER removes the appointing authority for every `[APPOINTED_BY:EXPEDITION_LEADER]` position — do not expose it to the agent.

### `create_room_zone` — confirmed
**Purpose.** Paint an Office / Bedroom / Dining Hall / Tomb / Meeting Area zone over a rectangle — in v50 rooms are civzones, and the manager and bookkeeper physically cannot do their jobs without an Office zone.

**API.** Confirmed shipped pattern, `/srv/df-bonsai/current/hack/scripts/internal/quickfort/zone.lua:356-386`:

```lua
-- create_room_zone(zone_type, x, y, z, width, height)
local bld, err = dfhack.buildings.constructBuilding{
  type = df.building_type.Civzone,
  subtype = df.civzone_type[zone_type],      -- 'Office', 'Bedroom', 'DiningHall', 'Tomb', ...
  abstract = true,
  pos = { x = x, y = y, z = z }, width = width, height = height,
  fields = { assigned_unit_id = -1,
             room = { x = x, y = y, width = width, height = height } } }
if not bld then return 'zone-failed: ' .. tostring(err) end
print('ZONE id=' .. bld.id .. ' type=' .. df.civzone_type[bld.type])
```
quickfort passes an explicit `extents` bitmap for non-rectangular zones and calls `dfhack.buildings.notifyCivzoneModified(bld)` after changing extents/size; for a plain rectangle neither is needed.

**Fields.** `zone_type` (string, `df.civzone_type` key). Confirmed keys on this build (from `/srv/df-bonsai/current/hack/lua/plugins/sort/places.lua:13-30`): MeetingHall, Bedroom, DiningHall, Pen, Pond, WaterSource, Dungeon, FishingArea, SandCollection, Office, Dormitory, Barracks, ArcheryRange, Dump, AnimalTraining, Tomb, PlantGathering, ClayCollection. `x`,`y`,`z` (int, top-left corner, map coords), `width`,`height` (int >= 1; an office of 3x3 around a chair is ample). Returns `zone_id` (int32).

**Observable.** `#df.global.world.buildings.other.ZONE` (or a scan of `world.buildings.all` for `df.building_civzonest:is_instance`) increases by one; the new building has `.type == df.civzone_type.Office` and `.assigned_unit_id == -1`; `dfhack.buildings.findCivzonesAt(xyz2pos(x,y,z))` returns it.

**Risk.** A zone is not a room until it contains the right furniture: the DF binary's own zone tooltip reads "An office or study is required for certain official tasks, such as approving work orders and bookkeeping. A chair or throne is required for the[m]". Painting an Office over bare rock produces a zone the manager will never use — this action must be paired with a `build_furniture(Chair)` inside its rectangle. Zones may not overlap arbitrarily (the bedroom tooltip warns against overlap); `constructBuilding` returns nil + err rather than throwing, so always check.

### `assign_room_to_unit` — confirmed
**Purpose.** Give an existing zone to a specific dwarf — this is what makes an Office belong to the manager and a Bedroom belong to a citizen. Deliberately separate from create_room_zone.

**API.** ```lua
-- assign_room_to_unit(zone_id, unit_id)
local bld  = df.building.find(zone_id)
local unit = df.unit.find(unit_id)
if not (bld and unit and df.building_civzonest:is_instance(bld)) then return 'bad-args' end
if not dfhack.buildings.setOwner(bld, unit) then return 'setowner-failed' end
```
`dfhack.buildings.setOwner(civzone, unit)` is documented ("Replaces the owner of the civzone. If unit is nil, removes ownership. Returns false in case of error."). The two-sided invariant it maintains is visible in shipped code — `/srv/df-bonsai/current/hack/scripts/entomb.lua:148-151` writes `tomb.assigned_unit_id = unit.id` AND `unit.owned_buildings:insert('#', tomb)`; `unit-link-utils.lua` frees rooms with `dfhack.buildings.setOwner(bld, nil)`.

**Fields.** `zone_id` (int32, from create_room_zone), `unit_id` (int32, live citizen). Returns bool.

**Observable.** `df.building.find(zone_id).assigned_unit_id == unit_id` AND the same building object appears in `df.unit.find(unit_id).owned_buildings`. Both must hold — if only one does, setOwner failed halfway and the room will not count. For a noble, `dfhack.buildings.getRoomDescription(bld, unit)` returns a non-empty quality label (e.g. "Office"), and the nobles screen's office indicator moves from NOBLES_OFFICE_MISSING to NOBLES_OFFICE_GOOD.

**Risk.** Assigning a zone that is already owned silently displaces the previous owner; read `getOwner` first. `unit.owned_buildings` is also where bedrooms/tombs live — do not clear it wholesale. Jealous nobles are upset by better rooms elsewhere, so blanket-assigning high-value rooms to commoners has a real morale cost once a baron exists.

### `unassign_room` — confirmed
**Purpose.** Free a room so it can be given to someone else, or so a dead/departed dwarf stops holding it.

**API.** ```lua
-- unassign_room(zone_id)
local bld = df.building.find(zone_id)
if not bld then return 'no-zone' end
dfhack.buildings.setOwner(bld, nil)
```

**Fields.** `zone_id` (int32). No unit argument — ownership is single-valued.

**Observable.** `bld.assigned_unit_id == -1` and the building no longer appears in the former owner's `unit.owned_buildings`.

**Risk.** None material. Note that a noble whose required office is removed will start generating unmet-requirement unhappiness; that is intended game feedback, not a bug.

### `reserve_room_for_role` — confirmed
**Purpose.** Bind a room to a POSITION rather than to a dwarf, so the office follows whoever currently holds it — the correct way to make "the manager's office" durable across replacements.

**API.** Use the shipped `preserve-rooms` plugin's public Lua API rather than hand-rolling; it already knows the promotion chains (SHERIFF→CAPTAIN_OF_THE_GUARD, EXPEDITION_LEADER→MAYOR) via `entity_position.replaced_by`.

```lua
-- reserve_room_for_role(position_code, zone_id)
local pr = require('plugins.preserve-rooms')
pr.assignToRole(position_code, df.building.find(zone_id))   -- nil bld clears the reservation
```
Source: `/srv/df-bonsai/current/hack/lua/plugins/preserve-rooms.lua:20-26`, which forwards to the C++ `preserve_rooms_assignToRole(group_codes, bld_id)`. Its `code_lookup` is rebuilt on SC_MAP_LOADED from `positions.own` of both `plotinfo.civ_id` and `plotinfo.group_id` entities.

**Fields.** `position_code` (string, case-insensitive — the plugin lowercases it; must be a code present in `code_lookup`). `zone_id` (int32) or nil/-1 to clear.

**Observable.** `require('plugins.preserve-rooms').parse_commandline{'status'}` (or `preserve_rooms_getState()`) reports a non-zero "Managing assignments for noble rooms" count; after vacate_position + assign_position the new holder's `owned_buildings` contains the same zone.

**Risk.** Requires the `preserve-rooms` plugin to be ENABLED — the API exists whether or not the feature is on, and calling it while disabled is a silent no-op. `assignToRole` only prints to stderr on an unknown code (it does not error), so check the return of the lookup yourself. This does NOT set the current owner; pair with assign_room_to_unit for immediate effect.

### `set_bookkeeper_precision` — inferred
**Purpose.** Set how precise the bookkeeper's stock counts should be — the second half of the administrative pair, and what makes item/stock observables trustworthy.

**API.** ```lua
-- set_bookkeeper_precision(level)
df.global.plotinfo.nobles.bookkeeper_settings = level   -- record_precision_level_type
```
Field location confirmed: `plotinfost` embeds `<compound type-name='plotinfo_positionst' name='nobles'/>` whose members are, in order, `flags` (uint32), `manager_cooldown` (int32, comment "0-1008", orig. `manager_job_delay`), `bookkeeper_cooldown` (int32, "0-1008"), `bookkeeper_precision` (int32), `bookkeeper_settings` (enum `record_precision_level_type`, orig. `bookkeeper_goal_precision_level`).

**Fields.** `level` (int 0..4, or the `df.record_precision_level_type` key). The DF binary carries exactly five UI labels — "Lowest Precision", "Low Precision", "Medium Precision", "High Precision", "Highest Precision" — matching the nobles-screen buttons 1-5. Default on a fresh fort is the lowest. Write only `bookkeeper_settings` (the GOAL); `bookkeeper_precision` is the achieved level and is the game's to move.

**Observable.** `df.global.plotinfo.nobles.bookkeeper_settings` reads back the new value; over game time `bookkeeper_precision` climbs toward it and `bookkeeper_cooldown` cycles in 0..1008, and a `df.job_type.UpdateStockpileRecords` job appears in `world.jobs.list` (this is exactly what DFHack's stockflow plugin watches for). The DF binary's own warning strings confirm the gate: "If you don't have a Bookkeeper, or they don't have an Office to work in, numbers may be approximate." and "Your bookkeeper needs to work in an office to improve precision".

**Risk.** Setting a high goal without an assigned BOOKKEEPER holding an Office burns the dwarf's time for no gain and will never converge. Do not write `bookkeeper_precision` directly — it is the game's accumulator and forging it makes the stocks screen lie without the underlying counts being real. The enum token names for `record_precision_level_type` are NOT confirmed on this build (the key table is string-pooled); use integers 0..4 or probe `df.record_precision_level_type` at runtime.

### `create_squad_for_position` — inferred
**Purpose.** Give a squad-bearing position (MILITIA_COMMANDER, MILITIA_CAPTAIN, CAPTAIN_OF_THE_GUARD) the squad it needs — without it the appointment exists but commands nothing.

**API.** ```lua
-- create_squad_for_position(position_code)
local ent = df.global.plotinfo.main.fortress_entity
local pos, asg
for _, p in ipairs(ent.positions.own) do if p.code == position_code then pos = p end end
for _, a in ipairs(ent.positions.assignments) do
  if pos and a.position_id == pos.id and a.histfig ~= -1 then asg = a; break end
end
if not asg then return 'position-vacant' end
if asg.squad_id ~= -1 then return 'already-has-squad' end
local sq = dfhack.military.makeSquad(asg.id)
```
`DFHack::Military::makeSquad(int)` is an exported symbol in libdfhack.so and takes an `entity_position_assignment` id — the sibling calls are `addToSquad(unit_id, squad_id, squad_pos)`, `removeFromSquad(unit_id)`, `updateRoomAssignments(...)`, `getSquadName(...)`.

**Fields.** `position_code` (string; only positions carrying `[SQUAD:n:...]` in the raws — MILITIA_COMMANDER `[SQUAD:10:militia-dwarf]`, MILITIA_CAPTAIN `[SQUAD:10:militia-dwarf]`, CAPTAIN_OF_THE_GUARD `[SQUAD:10:fortress guard]`). Precondition: the position must already be filled by assign_position.

**Observable.** `assignment.squad_id != -1`, and `df.squad.find(assignment.squad_id)` resolves; `dfhack.military.getSquadName(squad_id)` returns a name.

**Risk.** Calling makeSquad on a vacant assignment or one that already has a squad produces orphan squads. MILITIA_CAPTAIN is `[NUMBER:AS_NEEDED]` and `[APPOINTED_BY:MILITIA_COMMANDER]` and `[MILITARY_SCREEN_ONLY]` — it needs a commander to exist first and a freshly created assignment record, so it is strictly harder than the NUMBER:1 positions; treat it as a later tier.

### `observe_manager_pipeline` — confirmed
**Purpose.** The single diagnostic that explains why a game-year of work orders produced zero jobs: does a manager exist, does the manager have a usable office, is the cooldown running, and are the orders validated and active?

**API.** Read-only.

```lua
local ent = df.global.plotinfo.main.fortress_entity
local w = df.global.world
local mgr = dfhack.units.getUnitByNobleRole('MANAGER')
local office = false
if mgr then
  for _, b in ipairs(mgr.owned_buildings) do
    if df.building_civzonest:is_instance(b) and b.type == df.civzone_type.Office then office = true end
  end
end
local nval, nact, nord = 0, 0, #w.manager_orders.all
for _, o in ipairs(w.manager_orders.all) do
  if o.status.validated then nval = nval + 1 end
  if o.status.active then nact = nact + 1 end
end
local njob = 0; local j = w.jobs.list.next
while j do njob = njob + 1; j = j.next end
print(string.format('MGR has=%s office=%s cooldown=%d pop=%d orders=%d validated=%d active=%d jobs=%d',
  tostring(#ent.assignments_by_type.MANAGE_PRODUCTION > 0), tostring(office),
  df.global.plotinfo.nobles.manager_cooldown, #dfhack.units.getCitizens(true),
  nord, nval, nact, njob))
```

**Fields.** No arguments. Emits `has_manager` (bool), `manager_has_office` (bool), `manager_cooldown` (int32 0..1008), `citizens` (int), `orders` (int), `orders_validated` (int), `orders_active` (int), `jobs` (int).

**Observable.** THIS IS THE ANSWER TO THE QUESTION THAT MATTERS. Yes — an unassigned MANAGER prevents manager_orders from becoming jobs, and the evidence is first-party from the shipped build, not the wiki. (1) `/srv/df-bonsai/current/data/vanilla/vanilla_entities/objects/entity_default.txt:637` ships this DESCRIPTION on POSITION:MANAGER — "The manager handles work orders. Once your fortress reaches a certain population, the manager must work in an office to validate work orders." — plus `[RESPONSIBILITY:MANAGE_PRODUCTION]` and `[REQUIRED_OFFICE:1]`. (2) `strings /srv/df-bonsai/current/dwarfort` contains the UI empty-state "A manager is required to coordinate" (rendered next to "There are no active work orders."), the workshop tooltip "A manager is required to add work orders to the shop.", and the work-order tooltip "All work orders must be validated by the manager before they become [active] ... has not been validated by the manager.  A manager can be employed in the nobles [and administrato]rs menu, and they must have an assigned office where they will work to validate". (3) The binary also carries the texture ids WORK_ORDERS_VALIDATED / WORK_ORDERS_NOT_VALIDATED alongside WORK_ORDERS_READY / CHECKING / ACTIVE, i.e. validation is a first-class order state. (4) DFHack itself encodes the rule: `/srv/df-bonsai/current/hack/scripts/gui/extended-status.lua:38-40` defines `has_manager()` as `#df.historical_entity.find(df.global.plotinfo.group_id).assignments_by_type.MANAGE_PRODUCTION > 0` and renders queued bed orders as "N queued - needs manager" when it is false. (5) The order-side field exists: `manager_order.status` is a `manager_order_status` bitfield (symbol `df::bitfield_traits<df::manager_order_status>::bits` in libdfhack.so) with bits `validated` and `active` — `hack/scripts/workorder.lua:278-279` names both (`order.status.validated`, `order.status.active`) and `hack/lua/plugins/orders.lua:196` gates on `order.status.active`. (6) The office requirement is population-gated, the manager requirement is not: the wiki puts the office threshold at 20 citizens, our fort ran the whole year at 7, and our dispatcher never set `status.validated` — so the orders sat at `validated=false` forever with `amount_left` never falling, which is exactly the measured `workorders_done = 0`. Expect this probe to print `has=false office=false orders=N validated=0 active=0` on the pinned save today, and `has=true ... validated>0` after assign_position('MANAGER', id) + create_room_zone('Office') + a chair + assign_room_to_unit.

**Risk.** Do not 'fix' this by writing `order.status.validated = true` from the dispatcher — `workorder.lua` deliberately comments those two writes out with the note "ignoring", and forging validation gives the agent a capability no human player has while also skipping whatever bookkeeping DF does at validation time (the manager gains Organizer experience at validation, not completion). Fix it by appointing a manager. Also note our current `add_workorder` writes a `df.manager_order` without setting `id` (so `manager_orders.manager_order_next_id` never advances and every order shares id 0), without `frequency`, and without `material_category` — `gui/extended-status.lua:49-57` and `internal/quickfort/stockflow.lua:639-641` show the full correct construction. That is a second, independent reason the orders were dead.

### `remove_room_zone` — inferred
**Purpose.** Delete a zone the agent painted in the wrong place, so a bad office does not permanently occupy the tiles a good one needs.

**API.** ```lua
-- remove_room_zone(zone_id)
local bld = df.building.find(zone_id)
if not bld then return 'no-zone' end
dfhack.buildings.setOwner(bld, nil)      -- drop ownership first
dfhack.buildings.deconstruct(bld)
```

**Fields.** `zone_id` (int32).

**Observable.** `df.building.find(zone_id) == nil`; `dfhack.buildings.findCivzonesAt(pos)` no longer returns it; the former owner's `unit.owned_buildings` shrinks by one.

**Risk.** Deconstructing a zone that a location (tavern/temple/hospital) is attached to leaves the location dangling — quickfort's `set_location` shows zones can carry `location_id`/`site_id` and call `zone:uncategorize()`/`zone:categorize(true)`. Check `bld.location_id == -1` before removing. I did not confirm `dfhack.buildings.deconstruct` on an abstract civzone in this build; if it misbehaves, the safe fallback is to leave the zone and simply unassign it.

**Lane notes.** WHAT IS NOT POSSIBLE / DEAD ENDS

1. There is no DFHack API to assign a noble. I dumped every `DFHack::Units::` exported symbol from `/srv/df-bonsai/current/hack/libdfhack.so`: `getNoblePositions` (two overloads, unit and historical_figure), `getUnitByNobleRole`, `getUnitsByNobleRole` — all getters, no setter anywhere in the Units, Buildings or Military modules. Assignment must be done by writing `entity_position_assignment` + `historical_figure.entity_links` by hand. Say this plainly to anyone who expects a one-liner.

2. `make-monarch.lua` is the only shipped assign-a-position script and it is stale. It sets `assignment.histfig` but not `histfig2`, never touches `assignments_by_type`, emits no history event, and predates `position_vector_idx` / `assignment_vector_idx` (DFHack issue #2671 records exactly this). The maintained reference for the inverse operation — and therefore the field-by-field template to mirror — is `unassignMayor()` in `/srv/df-bonsai/current/hack/scripts/internal/emigration/unit-link-utils.lua`.

3. Positions the player cannot appoint, on this build's raws, and should stay off the allow-list: MAYOR is `[ELECTED]` with `[REQUIRES_POPULATION:50]`; BARON/COUNT/DUKE are `[APPOINTED_BY:MONARCH]` and arrive via the outpost liaison at 20 pop + created/exported wealth thresholds; OUTPOST_LIAISON and DIPLOMAT and MONARCH and GENERAL belong to the CIV entity (`plotinfo.civ_id`), not the site government; FORCED_ADMINISTRATOR is `[CONQUERED_SITE]` only; DUNGEON_MASTER and CAPTAIN_OF_THE_GUARD need `[REQUIRES_POPULATION:50]`. Writing these anyway is forging, not playing.

4. `entity_position.flags` in this build carries computed bits alongside the raw tokens. Confirmed in shipped Lua: `.ELECTED` (preserve-rooms.lua), `.IS_LAW_MAKER` and `.RULES_FROM_LOCATION` (emigrate-nobles.lua). The binary's flag key table also contains, in sequence, `IS_LAW_MAKER, HAS_RESPONSIBILITIES, IS_LEADER, IS_DIPLOMAT, HAS_MET_POP_REQ, HAS_BEEN_REPLACED, HAS_RECEIVED_POSITIONS, HAS_MET_MARKET_REQ`. If `HAS_MET_POP_REQ` / `HAS_MET_MARKET_REQ` are what I think they are, they are the game's own precondition gates and should be the first check in assign_position — but I did not confirm them on a live save, so probe them before relying on them. This matters concretely: MANAGER, BOOKKEEPER, BROKER, CHIEF_MEDICAL_DWARF, HAMMERER, CHAMPION and DUNGEON_MASTER all carry `[REQUIRES_MARKET]` in the raws, and I could not determine offline whether a 7-dwarf embark satisfies it. Run `for _,p in ipairs(ent.positions.own) do print(p.code, p.flags.HAS_MET_POP_REQ, p.flags.HAS_MET_MARKET_REQ) end` on the pinned save before building anything on top of assign_position.

5. `positions` compound field order, read out of the libdfhack string table: `own, site, conquered_site, assignments, next_position_id, next_assignment_id, possible_evaluate, possible_succession, possible_appointable, possible_elected, possible_claimable`. The `possible_*` vectors look exactly like the game's own cached candidate lists and would be the cleanest precondition source of all — I could not confirm their element type offline. Worth ten minutes of probing; if `possible_appointable` holds position ids, assign_position gets a perfect gate for free.

6. Rooms are civzones in v50, not building-rooms. Anything you remember about "make this chair into an office" from pre-v50 is wrong here: `df.civzone_type.Office`, painted with `constructBuilding{type=df.building_type.Civzone, abstract=true}`, owned via `assigned_unit_id` + `unit.owned_buildings`. The furniture requirement did not go away though — the DF binary's zone tooltip is explicit that "A chair or throne is required". An Office zone with no chair is a no-op, and that is a very easy way for the agent to think it succeeded while nothing changes.

7. Version quirk worth knowing: `assignments_by_type` was declared `count="25"` in older df-structures, matching a 25-item `entity_position_responsibility`. This build's enum runs to at least 41 (…HEALTH_MANAGEMENT, ESPIONAGE, ADVISE_LEADERS, OVERSEE_LEADER_HOUSEHOLD, MANAGE_ANIMALS, MANAGE_LEADER_HOUSEHOLD_FOOD, PREPARE_LEADER_MEALS, MAINTAIN_SEWERS, FOOD_SUPPLY, FIRE_SAFETY, JUDGE, BUILDING_SAFETY, CONSTRUCTION_PERMITS, MAINTAIN_ROADS, MAINTAIN_BRIDGES, MAINTAIN_TUNNELS, DELIVER_MESSAGES). Several early members (MEET_WORKERS, TRADE, ESTABLISH_COLONY_TRADE_AGREEMENTS) are string-pooled and did not show up in my strings dump but are provably present because the raws use those exact tokens. Always index `assignments_by_type` by name.

8. Responsibility → position map for this build's MOUNTAIN entity, which is what actually decides who can do what: MANAGE_PRODUCTION → MANAGER (the work-order gate). ACCOUNTING → BOOKKEEPER (stock precision). TRADE → BROKER. HEALTH_MANAGEMENT → CHIEF_MEDICAL_DWARF. LAW_ENFORCEMENT → SHERIFF, then CAPTAIN_OF_THE_GUARD. EXECUTIONS → HAMMERER (`[EXECUTION_SKILL:HAMMER]`). MILITARY_STRATEGY → MILITIA_COMMANDER. MEET_WORKERS + RECEIVE_DIPLOMATS + MILITARY_GOALS → EXPEDITION_LEADER, inherited by MAYOR via `[REPLACED_BY:MAYOR]`. ESPIONAGE + MANAGE_ANIMALS → DUNGEON_MASTER. BUILD_MORALE → CHAMPION. DELIVER_MESSAGES → MESSENGER. Room requirements that actually bite a young fort: MANAGER `[REQUIRED_OFFICE:1]` and BOOKKEEPER `[REQUIRED_OFFICE:1]` — value 1, i.e. any office at all, versus SHERIFF at 100, CAPTAIN_OF_THE_GUARD/DUNGEON_MASTER at 250 and MAYOR/BARON at 500.

9. Ordering constraint for the fix: EXPEDITION_LEADER must be held (it is, on our save) before MANAGER can be appointed, because the raws say `[APPOINTED_BY:EXPEDITION_LEADER]` / `[APPOINTED_BY:MAYOR]`. So the minimal repair sequence is assign_position('MANAGER', best_organizer) → create_room_zone('Office', 3x3 near the dwarves) → build a Chair inside it (other lane) → assign_room_to_unit(office, manager) → optionally reserve_room_for_role('MANAGER', office). Do the same again for BOOKKEEPER with its own office, then set_bookkeeper_precision.

10. Second, independent bug found while chasing the manager: our `add_workorder` in `lab_agent/bonsai_lab_agent/dfhack/bonsai-apply-actions.lua:156-169` constructs a `df.manager_order` with only `job_type`, `amount_left`, `amount_total`. It never assigns `mo.id` from `world.manager_orders.manager_order_next_id` (so every order in the fort shares id 0), never sets `frequency` (`df.workquota_frequency_type.OneTime`), and never sets `material_category`. The shipped correct construction is five lines in `hack/scripts/gui/extended-status.lua:49-57` (`order.id = ...manager_order_next_id; ...next_id = id + 1; order.frequency = df.workquota_frequency_type.OneTime; order.material_category.wood = true`). Fixing the manager alone may not be enough — fix both.

---

## Lane 3 — self-rated confidence: high

### `workorder_create` — confirmed
**Purpose.** Queue one manager work order — the atomic unit of "keep making X" standing orders.

**API.** Route A (PREFERRED, pure Lua, no files): the shipped module /srv/df-bonsai/current/hack/scripts/workorder.lua is `--@ module=true` and exposes create_orders/preprocess_orders/fillin_defaults. It is orders.cpp transliterated to Lua and consumes EXACTLY the orders-plugin JSON object.

  local wo = reqscript('workorder')
  local o = {                       -- one validated order object (see fields)
    id = -1,                        -- local handle only; remapped to world.manager_orders.manager_order_next_id
    job = 'ConstructBed', amount_total = 10, frequency = 'Daily',
    material_category = {'wood'},
    item_conditions = {{condition='AtLeast', flags={'empty','food_storage'}, value=5}},
  }
  local list = wo.preprocess_orders({o})   -- MUST be called with amount_total already an integer
  wo.fillin_defaults(list)                 -- injects frequency='OneTime' when absent
  wo.create_orders(list, true)             -- quiet=true

Route B (plugin, file-mediated): write the array to <DF>/dfhack-config/orders/<name>.json then `dfhack.run_command('orders','import',name)`. Route B is the only path that supports reaction_id / contains / min_dimension (Route A hardcodes min_dimension=-1, reaction_id=-1 and silently drops `contains` — read at hack/scripts/workorder.lua).

The raw struct route (what bonsai-apply-actions.lua does today, `df.manager_order:new()` + set job_type/amount) works but reproduces none of the filtering, so prefer Route A.

**Fields.** JSON Schema (draft-07) for ONE order. Reject, do not coerce. `amount_total` MUST be integer — see risk.

{"$schema":"http://json-schema.org/draft-07/schema#","type":"object",
 "required":["job","amount_total","frequency"],"additionalProperties":false,
 "properties":{
  "id":{"type":"integer"},
  "job":{"type":"string","enum":["<df.job_type key>"]},
  "reaction":{"type":"string","pattern":"^[A-Z0-9_]+$"},
  "item_type":{"type":"string"},
  "item_subtype":{"type":"string"},
  "material":{"type":"string","pattern":"^[A-Z0-9_]+(:[A-Z0-9_]+){0,2}$"},
  "material_category":{"type":"array","items":{"type":"string"},"uniqueItems":true,"minItems":1},
  "item_category":{"type":"array","items":{"type":"string"}},
  "meal_ingredients":{"type":"integer","minimum":2,"maximum":4},
  "amount_total":{"type":"integer","minimum":0,"maximum":32767},
  "amount_left":{"type":"integer","minimum":0,"maximum":32767},
  "frequency":{"enum":["OneTime","Daily","Monthly","Seasonally","Yearly"]},
  "is_active":{"type":"boolean"},"is_validated":{"type":"boolean"},
  "workshop_id":{"type":"integer","minimum":0},
  "max_workshops":{"type":"integer","minimum":0,"maximum":64},
  "item_conditions":{"type":"array","maxItems":8,"items":{"$ref":"#/definitions/itemcond"}},
  "order_conditions":{"type":"array","maxItems":4,"items":{"type":"object",
     "required":["order","condition"],"additionalProperties":false,
     "properties":{"order":{"type":"integer"},
                   "condition":{"enum":["Activated","Completed"]}}}}},
 "definitions":{"itemcond":{"type":"object","required":["condition","value"],
   "additionalProperties":false,"properties":{
    "condition":{"enum":["AtLeast","AtMost","GreaterThan","LessThan","Exactly"]},
    "value":{"type":"integer","minimum":0,"maximum":100000},
    "item_type":{"type":"string"},"item_subtype":{"type":"string"},
    "material":{"type":"string"},
    "flags":{"type":"array","items":{"type":"string"},"uniqueItems":true,"maxItems":6},
    "bearing":{"type":"string"},
    "reaction_class":{"type":"string"},
    "reaction_product":{"type":"string"},
    "tool":{"type":"string"},
    "min_dimension":{"type":"integer"},
    "reaction_id":{"type":"string"},
    "contains":{"type":"array","items":{"type":"string"}}}}}}

Enum members CONFIRMED on this build (df.workquota.xml + strings in hack/libdfhack.so):
  frequency workquota_frequency_type = NONE(-1) OneTime Daily Monthly Seasonally Yearly
  condition logic_condition_type     = NONE(-1) AtLeast AtMost GreaterThan LessThan Exactly Not
  order cond workquota_order_condition_type = NONE(-1) Activated Completed

MATERIAL FILTERS — two DIFFERENT mechanisms, do not conflate:
  (a) order.material_category  -> df.manager_order.material_category, bitfield job_material_category.
      Names CONFIRMED in use by hack/data/orders/*.json: wood, plant, cloth, silk, yarn, strand,
      leather, bone, shell.  This is how the shipped library says "make it from wood/leather":
        ConstructBed  + material_category:["wood"]
        MakeArmor     + material_category:["leather"]
        WeaveCloth    + material_category:["silk"]
  (b) order.material -> mat_type/mat_index via dfhack.matinfo.find(token). Token grammar
      CONFIRMED in the library: "INORGANIC" (= any stone/metal), "INORGANIC:IRON",
      "INORGANIC:STEEL", "INORGANIC:BISMUTH_BRONZE", "GLASS_GREEN", "GLASS_CLEAR",
      "GLASS_CRYSTAL". This is how you say "make it from iron".
      "make it from oak" = "PLANT_MAT:OAK:WOOD" (OAK confirmed at
      data/vanilla/vanilla_plants/objects/plant_standard.txt:1083, material WOOD at :1087) —
      matinfo will resolve it, but see risk.

item_subtype is the raws itemdef id TOKEN, e.g. "ITEM_AMMO_BOLTS", "ITEM_TOOL_HONEYCOMB";
resolved through df.itemdef_<lower(item_type)>st. reaction is the raws REACTION code, e.g.
"BREW_DRINK_FROM_PLANT", "MAKE_MEAD", "STEEL_MAKING" (33 codes are exercised by the library;
the full vanilla set is in data/vanilla/vanilla_reactions/objects/reaction_*.txt).
amount_total = 0 means INFINITE repeat (workorder.lua prints "Queuing X infinitely").

**Observable.** for _,o in ipairs(df.global.world.manager_orders.all) do ... end — the new order appears with .id == the pre-call world.manager_orders.manager_order_next_id, .job_type == df.job_type[job], .amount_total == amount, .frequency == df.workquota_frequency_type[freq], #o.item_conditions == len(item_conditions). Progress = amount_total - amount_left, which is exactly the `worders` field already emitted by bonsai-observe.lua:34-38. A never-worked order shows amount_left == amount_total forever; a blocked one shows o.status.active == false.

**Risk.** CRITICAL, and it is in the code path we would naturally reuse: hack/scripts/workorder.lua preprocess_orders() does `elseif type(order.amount_total)=="string" then local fn = _ENV[order.amount_total] or load(order.amount_total)` and then CALLS it. Handing an agent-supplied string through that is arbitrary Lua execution with full DFHack privilege — it defeats the whole anti-forgery model in game_scorer.py. The schema above forces amount_total to an integer; the dispatcher must additionally assert type(o.amount_total)=='number' immediately before preprocess_orders. Second risk: unbounded order spam — cap orders created per round and total manager_orders. Third: an order whose conditions can never be met generates job-cancellation spam forever and depresses nothing measurable, so it is a silent no-op, not an error.

### `workorder_import_library` — confirmed
**Purpose.** Adopt a whole curated standing-order collection in one action — the fastest path from "nothing brewed all year" to a self-stocking fort.

**API.** dfhack.run_command('orders','import','library/basic')

Six collections ship at /srv/df-bonsai/current/hack/data/orders/: basic.json (228 orders across all six; basic covers meals, booze/mead, thread/cloth/dye, pots/bins/jugs/buckets, bags, crafts, mechanisms/cages, splints/crutches, lye/soap, ash/potash, beds/wheelbarrows/minecarts, paper/scrolls), furnace.json, military.json, smelting.json, rockstock.json, glassstock.json. Import ADDS to the current set, it does not replace. `orders list` enumerates available names.

**Fields.** {"collection": {"enum": ["library/basic","library/furnace","library/smelting","library/military","library/rockstock","library/glassstock"]}}  — allow-list only. Never pass an agent string through: the plugin's is_safe_filename permits any alnum/space/dot/hyphen/underscore name and reads it off disk.

**Observable.** #df.global.world.manager_orders.all jumps by the collection size (basic = 47 orders; all six = 228). Each imported order carries frequency 'Daily' and a non-empty item_conditions vector.

**Risk.** library/basic assumes a fort large enough to staff it — the docs say import it right after the first migration wave. On a 7-dwarf fort it queues dozens of orders nobody can work, which is harmless but drowns any signal about the agent's own choices. library/furnace and library/military burn fuel aggressively.

### `workorder_set_amount` — confirmed
**Purpose.** Raise or lower how many of a thing is still to be made without deleting and re-creating the order.

**API.** local o = <order from world.manager_orders.all>
o.amount_left  = n
o.amount_total = n   -- keep both in step; the scorer reads total-left as progress
-- 0 == infinite repeat

**Fields.** {order_id: int (matches o.id), amount: int 0..32767}

**Observable.** o.amount_left == amount and o.amount_total == amount on the next read; bonsai-observe.lua `worders` moves by the delta.

**Risk.** Writing amount_total below amount_left makes progress (total-left) negative; the observe script already clamps with math.max(0,...) but the agent could farm apparent progress by shrinking total. Clamp amount_left <= amount_total evaluator-side.

### `workorder_set_frequency` — confirmed
**Purpose.** Turn a one-off order into a standing order (or stop it repeating).

**API.** o.frequency = df.workquota_frequency_type[freq]  -- OneTime|Daily|Monthly|Seasonally|Yearly

**Fields.** {order_id: int, frequency: enum[OneTime,Daily,Monthly,Seasonally,Yearly]}

**Observable.** df.workquota_frequency_type[o.frequency] == freq. A repeating order re-arms: amount_left returns to amount_total at each period boundary, and o.finished_year / o.finished_year_tick record the last completion.

**Risk.** Repeating orders starve one-time orders of manager attention — that is exactly why `orders sort` exists. Pair with workorder_sort.

### `workorder_cancel` — confirmed
**Purpose.** Remove a single bad or obsolete order.

**API.** for i,o in ipairs(df.global.world.manager_orders.all) do
  if o.id == order_id then df.global.world.manager_orders.all:erase(i); o:delete(); break end
end

**Fields.** {order_id: int}

**Observable.** #world.manager_orders.all drops by 1 and no member has .id == order_id.

**Risk.** Deleting an order that other orders reference through order_conditions leaves a dangling order_id; those dependents will never activate. Sweep order_conditions for the id first, or refuse.

### `workorder_clear_all` — confirmed
**Purpose.** Wipe the order queue — the only clean way to recover from a queue the agent has poisoned.

**API.** dfhack.run_command('orders','clear')

**Fields.** {} (no arguments)

**Observable.** #df.global.world.manager_orders.all == 0.

**Risk.** Irreversible within an episode and destroys any imported library. Should be rate-limited to at most once per episode, or omitted from the agent surface entirely and kept as an evaluator reset primitive.

### `workorder_sort` — confirmed
**Purpose.** Stop repeating orders from permanently blocking one-time orders — a real thing human players automate.

**API.** dfhack.run_command('orders','sort')
-- sort order per docs/tools/orders.txt: one-time first, then Yearly, Seasonally, Monthly, Daily

**Fields.** {} (no arguments)

**Observable.** world.manager_orders.all is reordered so indices ascend by frequency rank; read df.workquota_frequency_type[o.frequency] across the vector and assert monotonicity.

**Risk.** None known. Cheap and idempotent; the docs recommend running it on a daily repeat.

### `workorder_recheck` — confirmed
**Purpose.** Force the manager to re-evaluate conditions on orders that were true when started but are now false — the documented cure for job-cancellation spam.

**API.** dfhack.run_command('orders','recheck')       -- all recheckable orders
dfhack.run_command('orders','recheck','this') -- only the order whose conditions page is open (needs the UI; not usable headless)

**Fields.** {} (no arguments; the 'this' variant requires an open viewscreen and should not be exposed)

**Observable.** Orders that had o.status.active == true and #o.item_conditions > 0 flip to o.status.active == false ("Checking"). That predicate is exactly can_recheck() in hack/lua/plugins/orders.lua:193-197.

**Risk.** Momentarily deactivates working orders; if called every round it can keep an order permanently in Checking and produce zero output. Rate-limit to once per in-game day.

### `workorder_add_item_condition` — confirmed
**Purpose.** Express the owner's standing order verbatim — "only run this while I have at least 5 free barrels", "stop at 3000 drinks".

**API.** local c = df.manager_order_condition_item:new()
c.compare_type = df.logic_condition_type.AtLeast   -- AtLeast|AtMost|GreaterThan|LessThan|Exactly
c.compare_val  = 5
c.flags2.empty = true; c.flags3.food_storage = true  -- set through reflection, see fields
-- optional narrowing:
-- c.item_type = df.item_type.DRINK
-- c.item_subtype = <def>.subtype
-- local m = dfhack.matinfo.find('INORGANIC:IRON'); c.mat_type, c.mat_index = m.type, m.index
-- c.metal_ore = <index into world.raws.inorganics.all>       (JSON key "bearing")
-- c.reaction_class = 'DYE_MAT'                                (JSON "reaction_class")
-- c.has_material_reaction_product = 'DRINK_MAT'               (JSON "reaction_product")
-- c.has_tool_use = df.tool_uses.LIQUID_CONTAINER              (JSON "tool")
o.item_conditions:insert('#', c)

The THREE canonical standing-order idioms, lifted verbatim from hack/data/orders/basic.json:
  keep 5 free food containers : {condition:'AtLeast', flags:['empty','food_storage'], value:5}
  stop at 3000 drinks         : {condition:'AtMost',  item_type:'DRINK', value:3000}
  need 15 brewable plants     : {condition:'AtLeast', item_type:'PLANT',
                                 reaction_product:'DRINK_MAT', flags:['unrotten'], value:15}

**Fields.** {order_id:int, condition:enum[AtLeast,AtMost,GreaterThan,LessThan,Exactly], value:int,
 item_type?:str, item_subtype?:str, material?:str, flags?:[str], bearing?:str,
 reaction_class?:str, reaction_product?:str, tool?:str}

Struct fields on this build (df.workquota.xml, manager_order_condition_item):
  compare_type(logic_condition_type) compare_val(int32) item_type(item_type)
  item_subtype(int16) mat_type(int16) mat_index(int32) flags1 flags2 flags3
  (bitfields job_item_flags1..3) flags4(uint32) flags5(uint32) reaction_class(string)
  has_material_reaction_product(string) metal_ore(int32->inorganic_raw)
  min_dimension(int32) contains(vector<int32>) reaction_id(int32->reaction)
  has_tool_use(tool_uses) dye_color(int32->descriptor_color)

FLAG NAME VALIDATION — do NOT hardcode a bit list. Build it at runtime, the way the
shipped hack/lua/gui/materials.lua:351-358 does:
  local map = {}
  for i=1,5 do if not df['job_item_flags'..i] then break end
    for _,f in ipairs(df['job_item_flags'..i]) do if f then map[f]='flags'..i end end end
  -- then: c[map[name]][name] = true, and reject any name not in map
The 31 flag names PROVEN to import (they appear in hack/data/orders/*.json) are:
  allow_melt_dump body_part bone collected cookable dye dyeable empty food_storage
  glass_making hair_wool hard leather melt_designated metal millable non_absorbent
  non_economic non_pressed plant processable processable_to_barrel sand_bearing shell
  silk soap solid totemable unrotten yarn
Same runtime-reflection rule applies to material_category (bitfield job_material_category)
and to tool (enum df.tool_uses — LIQUID_CONTAINER, FOOD_STORAGE, SMALL_OBJECT_STORAGE,
MEAL_CONTAINER, TRACK_CART, HEAVY_OBJECT_HAULING ... all read out of hack/libdfhack.so).

**Observable.** #o.item_conditions grows by 1; df.logic_condition_type[c.compare_type] and c.compare_val read back. Behavioural proof: the order's o.status.active toggles false when the condition stops holding, and the item count the condition guards (e.g. drink_count in EpisodeObs) stops climbing at the AtMost bound instead of running away.

**Risk.** A misspelled flag name is the failure mode that matters. Through Route A (workorder.lua set_flags_from_list) an unrecognised name qerrors and kills the WHOLE order; through Route B (orders import) the plugin drops just that condition and imports the order UNGUARDED — which is worse, because the agent then gets an order with no brake on it. Validate names before dispatch, in both routes. Also: min_dimension, reaction_id and contains cannot be set through Route A at all (workorder.lua pins them to -1 and never touches contains).

### `workorder_remove_item_condition` — confirmed
**Purpose.** Loosen an order the agent over-constrained so it can actually run.

**API.** local c = o.item_conditions[idx]
o.item_conditions:erase(idx)
c:delete()

**Fields.** {order_id:int, index:int 0-based}

**Observable.** #o.item_conditions drops by 1; a previously stuck order flips o.status.active to true within a manager cycle.

**Risk.** Removing the AtMost brake on a production order lets it run to the amount cap and flood stockpiles. Prefer editing compare_val over removing.

### `workorder_add_order_condition` — confirmed
**Purpose.** Chain orders — "only start weaving once the thread order has completed". This is real player-level sequencing and nothing in the current five-verb surface can express it.

**API.** local c = df.manager_order_condition_order:new()
c.order_id  = <id of the PREREQUISITE order, must already exist and not be this order>
c.condition = df.workquota_order_condition_type.Completed  -- or .Activated
this_order.order_conditions:insert('#', c)

**Fields.** {order_id:int (the dependent order), depends_on:int (prerequisite order id), condition:enum[Activated,Completed]}
Struct: manager_order_condition_order { order_id(int32->manager_order), condition(workquota_order_condition_type init Completed), flags(bitfield workquota_order_condition_flag, single bit `satisfied`) }

**Observable.** #this_order.order_conditions == 1 and c.flags.satisfied == false until the prerequisite fires, then true. The dependent order's status.active stays false until then.

**Risk.** Self-reference and dangling ids. Both orders.cpp and workorder.lua explicitly reject `id == self`; the evaluator must additionally verify depends_on exists in world.manager_orders.all, or the dependent order is dead forever with no error anywhere. Cycles (A waits on B waits on A) are not detected by DF — reject them evaluator-side with a topological check.

### `workorder_assign_workshop` — confirmed
**Purpose.** Pin an order to one specific building — "this forge, and only this forge, makes the steel breastplates".

**API.** o.workshop_id = <building.id>   -- -1 == any eligible workshop

**Fields.** {order_id:int, building_id:int | null}. Must be an existing df.building.find(building_id) whose type accepts the order's job; orders.cpp SKIPS the whole order on import when the building is missing.

**Observable.** o.workshop_id == building_id, and the generated df.job appears in that building's jobs vector rather than being distributed. The wiki notes the manager otherwise spreads jobs across every eligible workshop.

**Risk.** Pinning to a destroyed or wrong-type building yields an order that produces nothing and reports nothing. Validate df.building.find(id) ~= nil and that the building's workshop_type is in the job's eligible set before writing.

### `workorder_set_max_workshops` — confirmed
**Purpose.** Cap how many workshops chase one order at once, so a single order does not monopolise the whole industry.

**API.** o.max_workshops = n   -- df.workquota.xml comments this field: "0 is unlimited"

**Fields.** {order_id:int, max_workshops:int 0..64, 0 = unlimited}

**Observable.** o.max_workshops == n; at most n concurrent df.job instances trace back to this order (job.order_id, ref-target manager_order).

**Risk.** Setting 1 on a high-volume order serialises production and can look like the order is stalled. Low risk otherwise.

### `workshop_set_general_order_cap` — inferred
**Purpose.** Stop a workshop from being drafted for general manager orders so it stays free for hand-placed jobs — the vanilla "General work orders allowed" number.

**API.** local bld = df.building.find(building_id)
bld.profile.max_general_orders = n   -- 0 == take no general work orders

**Fields.** {building_id:int, max_general_orders:int 0..10}. Field confirmed in df-structures workshop_profile as `max_general_orders`, original name `maximum_allowed_general_work_orders`. Present on building_workshopst, building_furnacest and building_trapst (all expose the compound as `.profile`).

**Observable.** bld.profile.max_general_orders == n; with 0, no new manager-generated job appears in bld.jobs while manually placed jobs still do.

**Risk.** Setting 0 on every workshop silently halts the entire manager economy while every order still reads as queued — a very cheap way for a policy to look busy and produce nothing. Guard: refuse if it would zero the last workshop capable of a queued order's job.

### `workshop_block_general_orders` — inferred
**Purpose.** Hard-ban a workshop from general work orders (the boolean twin of the cap above).

**API.** local bld = df.building.find(building_id)
bld.profile.flags.block_general_orders = true

**Fields.** {building_id:int, blocked:bool}. Bitfield workshop_profile_flag has exactly ONE bit, `block_general_orders`, original name GENERAL_WORK_ORDER_BAN — confirmed present in this build's hack/libdfhack.so string table adjacent to the workshop_type key table.

**Observable.** bld.profile.flags.block_general_orders == true and the building stops receiving manager-generated jobs.

**Risk.** Same fort-wide stall risk as the cap. Also redundant with max_general_orders=0; exposing both invites the agent to set one and be surprised by the other.

### `workshop_set_skill_range` — confirmed
**Purpose.** Reserve a workshop for good crafters (or for novices to train on) — the vanilla skill slider DFHack surfaces as orders.skillrestrictions.

**API.** local bld = df.building.find(building_id)
bld.profile.min_level = 0      -- df.skill_rating index
bld.profile.max_level = 3000   -- 3000 is DF's documented upper cap (hack/lua/plugins/orders.lua:326)

**Fields.** {building_id:int, min_level:int, max_level:int}. min/max are df.skill_rating indices; max_level's init value in df-structures is 3000 meaning "no cap". The shipped overlay collapses adjacent ratings for screen width, but the underlying fields are plain ints.

**Observable.** bld.profile.min_level / .max_level read back. Behaviourally, only units whose skill rating for the job's skill falls in [min,max] take jobs at that building.

**Risk.** The slider is INERT while the workshop has an assigned master: hack/lua/plugins/orders.lua:282 gates the whole UI on `#bld.profile.permitted_workers == 0`. Setting min/max on a workshop that has permitted_workers changes nothing and gives the agent a silent no-op. Also min_level > max_level makes the workshop unusable by anyone.

### `workshop_block_labor` — confirmed
**Purpose.** Specialise a shared workshop — "this Craftsdwarf's does stone only, that one does bone" — which is the documented way to stop general orders scattering across every shop.

**API.** local bld = df.building.find(building_id)
bld.profile.blocked_labors[df.unit_labor.STONE_CRAFT] = true

**Fields.** {building_id:int, labor:str (df.unit_labor key), blocked:bool}. blocked_labors is a static bool array indexed by unit_labor (original name general_work_order_ban_profession). The labors that are MEANINGFUL per building are enumerated in hack/lua/plugins/orders.lua get_profile_labors(), verbatim on this build:
  Carpenters CARPENTER,TRAPPER | Farmers PROCESS_PLANT,MAKE_CHEESE,MILK,SHEARER,SPINNER,PAPERMAKING
  Masons STONECUTTER,STONE_CARVER | Craftsdwarfs STONE_CRAFT,WOOD_CRAFT,BONE_CARVE,WAX_WORKING,BOOKBINDING,EXTRACT_STRAND,LEATHER,CLOTHESMAKER,METAL_CRAFT,GLASSMAKER
  Jewelers CUT_GEM,ENCRUST_GEM | MetalsmithsForge/MagmaForge FORGE_WEAPON,FORGE_ARMOR,FORGE_FURNITURE,METAL_CRAFT,TRAPPER
  Butchers BUTCHER,DISSECT_VERMIN | Fishery FISH,CLEAN_FISH,DISSECT_FISH | Still BREWER,HERBALIST
  Quern/Millstone MILLER,PAPERMAKING | Ashery POTASH_MAKING,LYE_MAKING | Custom(ScrewPress) PRESSING,PAPERMAKING
  Furnaces Kiln/MagmaKiln SMELT,POTTERY,GLAZING

**Observable.** bld.profile.blocked_labors[labor] == true, and manager orders whose job maps to that labor stop being assigned to this building (hand-placed jobs still work — the docs are explicit that the restriction applies only to general manager work orders).

**Risk.** Blocking a labor at every workshop that could do it strands the corresponding orders with no visible error. Validate: after the write, at least one non-blocked building must remain for every queued order's labor.

### `workshop_assign_worker` — confirmed
**Purpose.** Make one dwarf the master of a workshop — the classic "legendary smith gets his own forge" play.

**API.** local bld = df.building.find(building_id)
bld.profile.permitted_workers:insert('#', unit_id)

**Fields.** {building_id:int, unit_id:int}. permitted_workers is stl-vector<int32_t> with ref-target unit.

**Observable.** #bld.profile.permitted_workers > 0 and the id is present; only that unit takes jobs at the building.

**Risk.** Assigning a worker DISABLES the skill-range slider (orders.lua gates on the vector being empty), so a previously-set min/max silently stops applying. Assigning a dead or non-citizen unit id leaves a workshop nobody can use. Validate against dfhack.units.getCitizens(true).

### `workshop_clear_workers` — confirmed
**Purpose.** Un-dedicate a workshop, re-enabling skill-based restriction and general access.

**API.** local bld = df.building.find(building_id)
bld.profile.permitted_workers:resize(0)

**Fields.** {building_id:int}

**Observable.** #bld.profile.permitted_workers == 0; the skill slider becomes live again (can_set_skill_level() in orders.lua returns true on this predicate).

**Risk.** None beyond losing the dedication. Idempotent.

### `workorder_export_snapshot` — confirmed
**Purpose.** Serialise the live order queue to the plugin's own JSON so the evaluator can diff intent against reality, and so a replay can show what the agent actually asked for.

**API.** dfhack.run_command('orders','export', name)
-- writes <DF>/dfhack-config/orders/<name>.json, the SAME schema the agent emits

**Fields.** {name: str, ^[A-Za-z0-9 ._-]{1,64}$ — the plugin's own is_safe_filename accepts alnum plus space, dot, hyphen, underscore}

**Observable.** The file exists and json.load() of it yields an array whose length == #world.manager_orders.all, with per-order id/job/frequency/amount_total matching the live structs. This is the cheapest possible round-trip proof that a dispatched order object was understood as written — export after create and compare to what was sent.

**Risk.** Writes a file per call; unbounded names from the agent would litter dfhack-config/orders. Have the evaluator, not the agent, choose the name (e.g. episode id). Note the export includes keys the importer never reads back (`name`, the human-readable order caption from Job::getManagerOrderName) — strip them before diffing.

**Lane notes.** WHERE THE FACTS CAME FROM (all on the 53.15-r2 container unless noted)
- /srv/df-bonsai/current/hack/scripts/workorder.lua — shipped, `--@ module=true`, is orders.cpp transliterated to Lua. This is the single highest-value file for this lane: it gives us a supported, file-free Lua entry point that consumes the exact orders-plugin JSON. Read it before writing any dispatcher code.
- /srv/df-bonsai/current/hack/data/orders/{basic,furnace,smelting,military,rockstock,glassstock}.json — 228 real orders. Every field name, enum value and material token I marked "confirmed" was read out of these with jq.
- /srv/df-bonsai/current/hack/lua/plugins/orders.lua — the workshop skill/labor restriction contract (profile.*) and can_recheck()/can_set_skill_level() predicates.
- /srv/df-bonsai/current/hack/docs/docs/tools/orders.txt — the plugin's own command surface and library descriptions.
- `strings` on hack/plugins/orders.plug.so gave the complete JSON key set the binary reads/writes; `strings` on hack/libdfhack.so confirmed every enum member list I quote exists in THIS build.
- df-structures (df.workquota.xml, df.building.xml) for the struct field lists.
The plugin self-reports version 53.15-r2-0-g425442d4.

THE JSON KEY SET, COMPLETE, AS THE 53.15-r2 BINARY HANDLES IT
  order level:     id job reaction item_type item_subtype material material_category
                   item_category meal_ingredients art{type,id,subid} hist_figure
                   amount_left amount_total is_active is_validated frequency
                   workshop_id max_workshops item_conditions order_conditions
                   (+ `name`, EXPORT ONLY — the importer never reads it back)
  item_conditions: condition value flags item_type item_subtype material bearing
                   reaction_class reaction_product tool min_dimension reaction_id contains
  order_conditions: order condition
There is nothing else. Any other key an agent sends is unknown to the plugin.

THINGS THAT ARE NOT POSSIBLE — say no rather than invent
- flags4 and flags5 on item conditions are marked TODO in orders.cpp and are never serialised. Same for the condition's `dye_color` field, and for the order's `finished_year`/`finished_year_tick` and `items` (job_reqst). Not expressible.
- Milking, shearing and cheesemaking CANNOT be given useful order conditions — the shipped docs say so outright and that is why library/basic omits them. Those need the autocheese / automilk / autoshear scripts instead, which is a different action lane.
- `orders recheck this` needs an open conditions viewscreen. Unusable headless. Only the bare `orders recheck` is available to us.
- Route A (workorder.create_orders) cannot set min_dimension, reaction_id or contains — it hardcodes -1/-1 and never touches contains. If the agent needs reagent-level conditions (the MAKE_MEAD "2 units of the reagent named honey" idiom) you MUST go through a file plus `orders import`.
- workorder.lua writes `order.hist_figure_id`, but df-structures puts that field inside the `specdata` compound (`specdata.hist_figure_id`), which is what orders.cpp uses. The Lua route's hist_figure handling looks broken on this build. Drop `hist_figure` from the agent schema; it only matters for artifact-naming orders.

THE ONE FINDING THAT IS A SECURITY BUG, NOT A CONTRACT
hack/scripts/workorder.lua preprocess_orders() contains:
    elseif type(order.amount_total)=="string" then
        local fn = _ENV[ order.amount_total ] or load(order.amount_total)
        ...
        order.amount_total = fn(order, orders)
`load()` on an agent-controlled string, then called. If we route agent-supplied order objects through that function without forcing amount_total to an integer first, an untrusted controller gets arbitrary Lua execution inside DFHack — which is precisely the thing lab_agent/bonsai_lab_agent/game_scorer.py's sanitize_actions exists to prevent. The schema in contract #1 rejects it; the dispatcher should also assert the type immediately before the call, because a schema change made a year from now should not be the only thing standing between us and that line.

VERSION QUIRKS AND GOTCHAS WORTH BUDGETING FOR
- A manager noble is NOT required today. The wiki's rule is that at 20+ citizens work orders stop being performed until a manager validates them, and the manager needs an office. The pinned save has 7 citizens, so the earlier "workorders_done stayed 0 all year" was not a manager problem — but it becomes a hard blocker the moment migration pushes the fort past 20. An `assign_noble` + `create_office_zone` pair belongs in whichever lane owns nobles.
- `amount_total = 0` means INFINITE, not zero. workorder.lua literally prints "Queuing X infinitely". An agent that writes 0 meaning "none" gets a perpetual order.
- The JSON `id` is a local handle only. On import every id is remapped to world.manager_orders.manager_order_next_id, and order_conditions are rewritten through that mapping. Agent-supplied ids must be treated as within-batch references, never as handles to existing orders.
- Do not hardcode the bit-name lists for job_item_flags1/2/3 or job_material_category. I could confirm the 31 flag names and 9 material categories that the shipped library actually uses, but the strings table in libdfhack.so is deduplicated and does not preserve bitfield ordering, so any full list I wrote out would be part guesswork. Enumerate them at runtime with the idiom in hack/lua/gui/materials.lua:351-358 and dump the result once into the repo as generated data — the same approach already used for tools/replay/enums_compact.json.
- Two different material mechanisms, and the shipped library is consistent about which to use: organics (wood, leather, cloth, silk, yarn, plant, bone, shell, strand) go through `material_category`; inorganics and glass go through `material` as a matinfo token. "Make it from iron" is `"material":"INORGANIC:IRON"` and is confirmed. "Make it from oak" as `"material":"PLANT_MAT:OAK:WOOD"` will resolve through dfhack.matinfo.find (OAK's WOOD material is confirmed in the raws) but the vanilla manager UI never offers wood species and the library never does it — I did not confirm the manager will fill such an order. Allow it in the schema, but have the dispatcher record it as a distinct outcome so we find out empirically instead of assuming.
- `orders import` adds, it never replaces. Importing library/basic twice doubles every order.

SUGGESTED SHAPE FOR OUR SIDE
game_scorer.ALLOWED_VERBS is a flat set of strings and _write_actions serialises to tab-separated `verb\targ1\targ2`. That format cannot carry a nested order object. The work-order lane needs a second channel: keep the tab file for the simple verbs, and write the structured ones as one JSON object per line (verb + args) to a sibling file that bonsai-apply-actions.lua reads with the shipped `json` module (require('json') is available — workorder.lua uses it). Validate against the schema in contract #1 on the Python side before it ever reaches Lua, and re-validate enum membership on the Lua side against live reflection, because the Python allow-list will drift from the build and the Lua one cannot.

---

## Adversarial reviews

### Review 1 — holds=False
The API call is real, but the contract is incomplete in exactly the way the dig-designation bug was, the observable is a tautology, and the "confirmed" rating is not honest.

WHAT SURVIVES (HIGH — read in this build):
- `dfhack.buildings.setOwner(civzone, unit)` exists; nil clears. Documented at `/srv/df-bonsai/current/hack/docs/docs/dev/Lua API.txt:2357` ("Replaces the owner of the civzone. If unit is nil, removes ownership."). Called with nil at `hack/scripts/fix/ownership.lua:41` and `hack/scripts/internal/emigration/unit-link-utils.lua:151`.
- `zone.assigned_unit_id` exists, -1 is the unowned sentinel: `hack/scripts/entomb.lua:391` (`tomb.assigned_unit_id == -1`), `hack/scripts/internal/quickfort/zone.lua:361` (created as `assigned_unit_id=-1`), `hack/scripts/store-owned.lua:41`.
- `unit.owned_buildings` is a vector of building POINTERS, indexed by `.id`: `fix/ownership.lua:38` `utils.linear_index(unit.owned_buildings, zone.id, 'id')`; `unit-link-utils.lua:150` `df.building.find(unit.owned_buildings[i].id)`.

WHY IT FAILS:

1. MISSING SIDE EFFECT, tombs — the strongest hit, confirmed in shipped code. `hack/scripts/entomb.lua:148-154` deliberately does NOT use setOwner. It writes `assigned_unit_id` and `owned_buildings` by hand and then sets `tomb.zone_settings.tomb.flags.no_pets = true` / `no_citizens = true`, with the comment "Make tomb zone unavailable for automatic assignment to other dead units." setOwner does not clear those bits. Free a tomb with `setOwner(zone,nil)` and `assigned_unit_id == -1` (the proposed observable PASSES) while the zone stays flagged closed to citizens — DF's auto-burial will never take it. Same class as designations that read back correctly and generate zero jobs.

2. MISSING SIDE EFFECT, the zone-enabled bit. `spec_sub_flag.active` is the room's on/off toggle (`quickfort/zone.lua:132` sets it true at creation, `:240` false for `active=false`). DFHack's own free-tomb search requires it: `entomb.lua:56` `if unit_id == -1 and not buil

**Correction.** VERB: unassign_room_owner
SCOPE: civzone types Bedroom, Office, DiningHall, Tomb ONLY (the four vectors in `fix/ownership.lua` zone_vecs). Barracks/dormitory ownership does not exist — route to a separate `unassign_squad_barracks` verb operating on `zone.squad_room_info`.
FIELDS: `zone_id: int` (building id, not a pointer — the dispatcher resolves it). Optional `reopen: bool = true`.

DISPATCHER (matches the style of bonsai-apply-actions.lua):

  local OWNABLE = {
      [df.civzone_type.Bedroom]=true, [df.civzone_type.Office]=true,
      [df.civzone_type.DiningHall]=true, [df.civzone_type.Tomb]=true,
  }
  local zone = df.building.find(act.zone_id)
  if not df.building_civzonest:is_instance(zone) then return fail('not_a_civzone') end
  if not OWNABLE[zone.type] then return fail('zone_type_not_ownable') end

  -- guard the silent-revert path before touching anything
  local pr = require('plugins.preserve-rooms')
  -- if the plugin is enabled and this zone carries a role reservation, clear it first
  -- (preserve_rooms_assignToRole(group_codes, -1)) or refuse; otherwise the background
  -- cycle re-assigns the room and our write vanishes with no error.

  local prev_owner = zone.assigned_unit_id            -- pre-state for the receipt
  dfhack.buildings.setOwner(zone, nil)                -- DO NOT test the return value

  if act.reopen ~= false then
      zone.spec_sub_flag.active = true                -- room must be enabled to be reusable
      if zone.type == df.civzone_type.Tomb then       -- setOwner leaves these set
          zone.zone_settings.tomb.flags.no_citizens = false
          zone.zone_settings.tomb.flags.no_pets = false
      end
  end

Batch form (freeing every room of one unit) must copy the shipped idiom, backwards with re-find by id, because setOwner mutates the vector being iterated:

  for i = #unit.owned_buildings-1, 0, -1 do
      local b = df.building.find(unit.owned_buildings[i].id)
      dfhack.buildings.setOwner(b, nil)
  end

OBSERVABLES, 

### Review 2 — holds=False
The field path is real, but three of the four load-bearing claims are wrong, and the one detail the researcher cited as supporting evidence (`whole=1`) actually falsifies their model.

WHAT SURVIVES. `building_civzonest.zone_settings.tomb.flags.{no_pets,no_citizens}` exists in this build. Confirmed two ways: /srv/df-bonsai/current/hack/scripts/entomb.lua:153-154 writes both, and df-structures defines `civzone_tomb_flag` (base uint32_t) with exactly two bits. The path is also current — hack/docs/docs/changelogs/news-dev.txt:1671 records the rename `zone_settings.tomb` -> `zone_settings.tomb.flags`.

REFUTATION 1 — the PURPOSE is unachievable with this API. These are a two-bit NEGATIVE filter on DF's automatic burial selection. There is no positive "only unit X" mode in the bitfield. A private mausoleum is `assigned_unit_id` (int32, init-value -1) plus the reciprocal `unit.owned_buildings` insert — entomb.lua:148-150. Setting both flags does not produce a noble's mausoleum; it produces a tomb nobody is auto-buried in. hack/docs/docs/tools/burial.txt says so verbatim for `burial -cp`: "automatic burial disabled for both citizens and pets, requiring manual assignment."

REFUTATION 2 — `whole=1` decodes against the researcher. df-structures df.building.xml:1019-1022 gives the bit order as bit0=`no_pets` (NOPET), bit1=`no_citizens` (NOCIV). So quickfort's Tomb default `flags.whole=1` means no_pets=TRUE, no_citizens=FALSE. The flags are not a symmetric pair; the DFHack-created default tomb already rejects pets and accepts citizens. Confirmed three independent ways: the XML bit order; quickfort/zone.lua:63-69 `parse_tomb_props`, which only ever writes `no_pets=false` (on `pets=true`) and `no_citizens=true` (on `citizens=false`) — both are deltas from a whole=1 baseline; and burial.lua's option matrix, where bare `burial` emits blueprint `T{ pets=true}` and `-c` emits `T{ }` (i.e. citizens-only IS the untouched default). The researcher quoted `whole=1` without decoding it.



**Correction.** WHAT IS ACTUALLY TRUE, and what to ship instead.

A. SEMANTICS (HIGH — df.building.xml:1019-1026 + quickfort/zone.lua:63-69 + burial.txt)

    civzone_tomb_flag : uint32_t
      bit 0  no_pets      (bay12 NOPET)
      bit 1  no_citizens  (bay12 NOCIV)

  Admission matrix, as the shipped `burial` tool encodes it:

    no_pets  no_citizens  whole  meaning                      burial flag
    -------  -----------  -----  ---------------------------  -----------
    false    false        0      communal: citizens + pets    (bare)
    true     false        1      citizens only  <-- DEFAULT   -c
    false    true         2      pets only                    -p
    true     true         3      no auto-burial; manual only  -cp

  Note whole=1 is the default for a DFHack-created tomb, so "communal crypt" is not
  the baseline the contract assumes — it is a state you must explicitly write.

B. PREFER THE SHIPPED SERIALISABLE FORMAT (the brief asks for this)

  DFHack already has a JSON-able schema for exactly this: the quickfort zone blueprint
  token, documented in hack/docs/docs/guides/quickfort-user-guide.txt:1650-1652 —
  zone letter `T` plus two boolean props expressed as deltas from the whole=1 default:

      T{citizens=false pets=true}

  `pets=true`      -> no_pets = false
  `citizens=false` -> no_citizens = true
  (omitted props leave the default; there is deliberately no `pets=false` /
   `citizens=true`, because those ARE the defaults — passing them raises
   "unhandled property".)

  burial.lua builds this string and calls
  `quickfort.apply_blueprint{mode='zone', pos=..., data=...}`.
  Use that for zone CREATION rather than constructing a civzone by hand.

C. CORRECTED CONTRACT — split it in two. The proposed verb conflates them.

  VERB set_tomb_admission (edit an EXISTING zone)
  args: zone_id:int, allow_citizens:bool, allow_pets:bool
  preconditions the dispatcher MUST enforce (union safety is not optional):

      local z = df.building.find(args.zone_id)
    

### Review 3 — holds=False
REFUTED on five independent counts, three of them fatal. The plugin and function do exist, but the contract's central claim is backwards, its observable is a write-back readback, and it omits the required side-effect step.

(1) FATAL — "bld=nil clears the binding" is FALSE; -1 means "use the UI-selected zone". Shipped Lua `/srv/df-bonsai/current/hack/lua/plugins/preserve-rooms.lua` maps `bld and bld.id or -1`. Disassembly of `preserve_rooms_assignToRole(lua_State*)` at 0x18300:
    18344: call luaL_checkinteger(L, 2)      ; arg2 = zone_id
    1834b: cmp  $0xffffffff,%eax             ; == -1 ?
    1834e: je   18560
    18560: mov  $0x1,%esi
    18568: call DFHack::Gui::getSelectedCivZone(color_ostream&, bool)
    18570: test %rax,%rax ; je 184df
    184df: ... xor %eax,%eax ; ret           ; ZERO lua results, no error, no printerr
So -1 = "the zone currently selected in the DF UI". Headless, with nothing selected, `assignToRole('MAYOR', nil)` is a SILENT NO-OP — it neither assigns nor clears, and returns nothing. This is the exact dig-designation failure shape the task warns about. The real clear path is an empty/blank code vector with a VALID zone: at 0x1841b an empty vector jumps to 0x186e0, which hashes `bld->id` (`movslq 0x50(%r13)`) into `noble_zones` and erases; the blank-string path at 0x18580 erases AND sets bit 0x8 at building offset 0x154. The overlay's `None` option (`value={''}`) is what drives this.

(2) FATAL — the missing side effect. `assignToRole` only writes the in-memory `noble_zones` map. The actual `DFHack::Buildings::setOwner(building_civzonest*, unit*)` calls live in `do_cycle` (0x16870, callsites 0x11e4d / 0x1338b), reached only from `plugin_onupdate` (0x17e40) after: world+map present, `World::isFortressMode()`, AND `world->frame_counter - cycle_timestamp > 0x6c` (108 ticks). Our driver runs PAUSED, so `frame_counter` never advances and the assignment never lands. The snippet as given changes nothing observable in our harness. You must call t

**Correction.** CORRECTED CONTRACT

VERB: assign_room_to_noble_role
PURPOSE: Bind an assignable civzone to a noble PROMOTION CHAIN (not a single position), so it follows whoever holds any office in that chain.

FIELDS
  code: string, case-insensitive. NOT a fixed enum — validate at runtime against
        `pr.code_lookup`, which is derived per-save from civ + group entity positions.
        Any code in a chain selects the WHOLE chain (baron/count/duke are one key).
  zone: df.building_civzonest, REQUIRED. Never pass nil.

MINIMAL LUA THAT ACTUALLY WORKS
  local pr = require('plugins.preserve-rooms')  -- must be required BEFORE SC_MAP_LOADED,
                                                -- else pr.code_lookup is {} and all calls fail

  local function assign_room_to_role(bld, code)
      if not df.building_civzonest:is_instance(bld) then return nil, 'not a civzone' end
      local group = pr.code_lookup[code:lower()]
      if not group then return nil, 'unknown role code' end  -- wrapper does NOT return here
      pr.preserve_rooms_assignToRole(group, bld.id)   -- explicit id; -1 is UI-selection, not clear
      pr.preserve_rooms_cycle()                       -- THE MISSING STEP; paused forts never cycle
      return group[1]                                 -- canonical key, e.g. MAYOR -> EXPEDITION_LEADER
  end

  local function clear_room_role(bld)
      pr.preserve_rooms_assignToRole({''}, bld.id)    -- blank code = erase; what the overlay's
      pr.preserve_rooms_cycle()                       -- 'None' option does
  end

If the pre-map-load require ordering cannot be guaranteed, rebuild the lookup yourself from
`df.historical_entity.find(df.global.plotinfo.civ_id).positions.own` and `.group_id`, grouping by
`replaced_by`, and call `pr.preserve_rooms_assignToRole(group, bld.id)` directly.

OBSERVABLE — use ownership, not the plugin's own map
  Primary (real):   dfhack.buildings.getOwner(bld)  /  bld.assigned_unit_id
                    This is what do_cycle actually mutates v

### Review 4 — holds=False
REFUTED on four counts. The one thing the researcher got right is the thing they were asked to worry about: there is NO missing side effect. Unlike dig designations, `name` is a plain display field with no dirty flag — `/srv/df-bonsai/current/hack/scripts/entomb.lua:129` writes `tomb.name = strTomb` bare on an already-linked live zone with no follow-up call, and `/srv/df-bonsai/current/hack/scripts/internal/quickfort/zone.lua:355-384` (`create_zone`) applies the name via `utils.assign(bld, data)` after `constructBuilding` with no re-categorize. So the assignment itself works. HIGH confidence. Everything else in the contract is wrong.

(1) WRONG OWNING TYPE. `name` is not a `building_civzonest` field; it is on the base `df.building`, so the verb is under-scoped by 3x. Confirmed on this build: `/srv/df-bonsai/current/hack/scripts/internal/quickfort/place.lua:339` reads `pile.name` over `world.buildings.other.STOCKPILE`, `place.lua:350` reads `shop.name` over `WORKSHOP_ANY` — the identical `if #x.name > 0` idiom as the civzone code — and `/srv/df-bonsai/current/hack/scripts/internal/quickfort/build.lua:1214-1268` funnels `props.name` into `utils.assign(bld, db_entry.props)` for arbitrary constructed buildings. The shipped guide `/srv/df-bonsai/current/hack/docs/docs/guides/quickfort-user-guide.txt:1808` states it outright: "all building types accept the `name` and `do_now` properties." Shipping `rename_zone` means the stockpile and workshop lanes will each duplicate it.

(2) THE OBSERVABLE IS NOT AN OBSERVABLE. "`bld.name` reads back" is reading the memory-mapped field we just wrote — structurally identical to the dig-designation bug, where `tile.designation.dig` also read back perfectly and produced zero jobs. The second half of the "observable" is a *negative* (`getName()` unchanged), which confirms nothing about the write. The contract therefore ships with no DF-derived confirmation at all, while calling itself confirmed.

(3) THE STATED PURPOSE IS UNSOUND — a name 

**Correction.** CORRECTED CONTRACT.

VERB: rename_building (NOT rename_zone)
PURPOSE: attach a human/agent-readable LABEL to any building. It is explicitly NOT the handle — `building.id` is the handle. Emit `{id, name}` pairs in the observation so the agent can address by id and read labels for context.
FIELDS:
  building_id : int32  — `df.building.id`, the authoritative handle
  name        : string — `df.building.name`, stl-string, raw bytes rendered as CP437. Sanitizer MUST enforce `^[A-Za-z0-9 _-]{1,32}$` and MUST reject a name already borne by another building (DF does not enforce uniqueness; we must, or the label is useless as a lookup key).
APPLIES TO: `building_civzonest`, `building_stockpilest`, all `WORKSHOP_ANY`/furnace types — anything in `df.global.world.buildings.all`. HIGH confidence (quickfort-user-guide.txt:1808 + place.lua:339,350 + build.lua:1268).

LUA (in bonsai-apply-actions.lua style):
  local bld = df.building.find(tonumber(a[2]))
  if bld then
    local n = tostring(a[3] or ''):gsub('[^%w _-]', ''):sub(1, 32)
    for _, o in ipairs(df.global.world.buildings.all) do
      if o.id ~= bld.id and o.name == n then n = '' end   -- collision: refuse
    end
    if #n > 0 then bld.name = n end
  end
No categorize/uncategorize, no flag, no rescan needed. HIGH confidence.

REAL OBSERVABLE (replace the tautology with these three, in order of strength):
  1. Uniqueness scan (HIGH, cheap, already in our pipeline): walk `df.global.world.buildings.all`, assert exactly one entry has `b.name == n` and that its `b.id` equals the requested id. This proves the label is usable as a lookup key — which the write-then-read never did.
  2. Save/load round-trip (strongest genuinely independent check): name, save, reload, re-scan. This proves DF serialised the field rather than that our pointer write merely stuck. INFERRED that `building.name` is savegame-persistent — I did not confirm serialisation from Lua.
  3. Do NOT use `dfhack.buildings.getName(bld)`. It calls DF's `building::g

### Review 5 — holds=False
The API name is real but the contract is wrong on the vector it names, wrong on its observable, and — the serious one — it omits a mandatory teardown step, which is the same class of bug as the `flags.designated` dig failure.

WHAT SURVIVES (verified on this build)
- `dfhack.buildings.deconstruct(building)` exists. Two independent confirmations: `/srv/df-bonsai/current/hack/docs/docs/dev/Lua API.txt:2431` ("Destroys the building, or queues a deconstruction job. Returns *true* if the building was destroyed and deallocated immediately"), and the exported symbol `_ZN6DFHack9Buildings11deconstructEPN2df8buildingE` in `/srv/df-bonsai/current/hack/libdfhack.so`. HIGH.
- `dfhack.buildings.findCivzonesAt(pos)` exists — Lua API.txt:2373, symbol `_ZN6DFHack9Buildings14findCivzonesAtEPSt6vectorIPN2df18building_civzonestESaIS4_EENS2_5coordE`. Note the doc says it returns a lua sequence **or nil if none** — not an empty table. HIGH.
- `building_civzonest` is the correct type (`hack/lua/plugins/zone.lua:992`, `plugins/dwarfvet.lua:119`). HIGH.
- "Abstract buildings are destroyed synchronously" is right in principle: the queue-a-job branch is gated on `isActual() && getBuildStage() > 0`, and df.building.xml:1059 defines `building_civzonest inherits-from='building'` while `building_actual` is a separate class — so a civzone takes the immediate path. HIGH.

DEFECT 1 — `world.buildings.other.ZONE_*` is not the index `findCivzonesAt` reads, and "ZONE_*" is not writable Lua.
`buildings_other_id` (df.building.xml:1778, vectors at 2554+) gives a civzone **three or four** simultaneous memberships: `IN_PLAY`, `ANY_ZONE` (original-name `civzone`), `ACTIVITY_ZONE` (original-name `civzone_activity`), and one of ~98 per-subtype buckets `ZONE_HOME … ZONE_DEPOT … ZONE_BEDROOM … ZONE_PEN` (the XML literally comments "98 different civzone subtypes: array of length BUILDING_CIVZONENUM"). DFHack's `findCivzonesAt` iterates **`ANY_ZONE`**. So the contract's two observables are asserted against differ

**Correction.** CORRECTED CONTRACT

VERB: delete_zone
PURPOSE: Remove a civzone the agent no longer wants, releasing its unit assignments and room ownership cleanly. (NOT for freeing tiles — zones do not occupy tiles. To reshape a zone, use a separate `resize_zone` verb that edits `zone.room.extents` then calls `dfhack.buildings.notifyCivzoneModified(zone)`; that preserves assignments and the location link.)

FIELDS: zone_id: int32 (the stable `building.id`, not a pointer — pointers do not survive between dfhack-run calls, and our dispatcher is invoked once per step).

PRECONDITION / GUARD: refuse when `zone.location_id ~= -1` (tavern/temple/library/hospital) — deleting those strands a site `abstract_building`.

REQUIRED SEQUENCE — the general_ref detach is mandatory and is the step the proposal omits:

    local function delete_zone(zone_id)
        local zone = df.building.find(zone_id)
        if not zone or not df.building_civzonest:is_instance(zone) then
            return false, 'no-such-zone'
        end
        -- deleting a zone that backs a site location would strand the abstract_building
        if zone.location_id ~= -1 then return false, 'zone-backs-a-location' end

        -- 1. unwind the UNIT side. deconstruct() erases only unit.owned_buildings, and
        --    only for units in world.units.active; it never walks unit.general_refs. Skip
        --    this and every pastured animal keeps a BUILDING_CIVZONE_ASSIGNED ref to a
        --    dead building id and can never be re-assigned. Mirrors the two-sided teardown
        --    in hack/lua/plugins/zone.lua:786 (detach_unit_or_vermin).
        for i = #zone.assigned_units - 1, 0, -1 do
            local u = df.unit.find(zone.assigned_units[i])
            if u then
                for r = #u.general_refs - 1, 0, -1 do
                    local ref = u.general_refs[r]
                    if df.general_ref_building_civzone_assignedst:is_instance(ref)
                            and ref.building_id == zone_id then
    

### Review 6 — holds=False
The field/type half of the contract is right, but the OBSERVABLE is refuted outright and the contract omits the step that actually makes furniture get built. Both stated "completion" signals are written synchronously by the very call being tested, on an UNCONSTRUCTED building. In /tmp/B1515.cpp (fetched from the DFHack 53.15-r2 tag; byte-identical to develop, 1742 lines, empty diff): `linkForConstruct` (line 1126) calls `linkBuilding(bld)` (line 1040), whose second statement is `world->buildings.all.push_back(bld)` — so the building is in `df.global.world.buildings.all` before any dwarf moves. And `constructWithFilters` (line 1209) ends with `add_building_to_all_zones(bld)` (line 1251) -> `building_into_zone_unidir` -> `zone->contained_buildings.push_back(bld)`. Its only gate is `is_suitable_building_for_zoning(bld)`, which is literally `return bld->canMakeRoom();` — a static property of the building TYPE, not a completion check. So `zone.contained_buildings` is populated the instant constructBuilding returns. Both proposed observables are the thing we wrote back; a scorer built on them counts intentions as achievements — the same failure class as the workorder counter that sat at 0. Second, the contract is not atomic: for Bed the auto-derived filter is `{item_type=df.item_type.BED, vector_id=df.job_item_vector_id.BED}` plus your mat_type/mat_index (read at /srv/df-bonsai/current/hack/lua/dfhack/buildings.lua:34). That matches an EXISTING bed ITEM; `material=` means "find a bed made of wood", not "make one from wood". The pinned embark has no beds/chairs/tables/coffins/cabinets, so the call succeeds, `#b.jobs > 0` is true, and nothing is ever built — precisely the observed "nothing developed" outcome. Third, the human's real placement path is buildingplan, which the contract never mentions; the shipped UI at /srv/df-bonsai/current/hack/lua/plugins/buildingplan/planneroverlay.lua:1463-1516 does constructBuilding -> addPlannedBuilding(bld) -> scheduleCycle(), and quic

**Correction.** WHAT SURVIVES (HIGH — read in /srv/df-bonsai/current/hack/lua/dfhack/buildings.lua)
All 15 named `df.building_type` members exist in `building_inputs` with the stated item_type/vector_id: Chair, Bed, Table, Coffin, Door, Box, Weaponrack, Armorstand, Cabinet, Statue, WindowGlass, WindowGem, Well, Cage, Chain. `dfhack.buildings.constructBuilding` exists (buildings.lua:481) and accepts pos OR x,y,z; type/subtype/custom; fields; width/height/direction; full_rectangle; and exactly one of items / filters / abstract / auto-derived. Filters ARE auto-derived via `getFiltersByType` when you pass none. `#b.jobs > 0` is structurally true for any successful non-abstract call (`bld->jobs.push_back(job)` in linkForConstruct) — but that makes it a tautology, not evidence.

FIX 1 — THE REAL COMPLETION OBSERVABLE (HIGH)
`bld.flags.exists` flips false->true when construction finishes. This is exactly how the shipped /srv/df-bonsai/current/hack/scripts/modtools/extra-gamelog.lua:148-160 logs "X was built": it caches `building.flags.exists` per id and emits on the transition. Corroborated by `markBuildingTiles` in B1515.cpp:993 — while `complete` is false it sets `occupancy.bits.building = tile_building_occ::Planned`, and only calls `bld->updateOccupancy()` when `getBuildStage() >= getMaxBuildStage()`. So:
  built      := bld.flags.exists == true            (equivalently getBuildStage() >= getMaxBuildStage())
  queued     := #bld.jobs > 0 and not bld.flags.exists
  waiting    := buildingplan.isPlannedBuilding(bld) -- planned, materials not yet found
Count `bld.flags.exists` per building_type across `df.global.world.buildings.all` at T0 and T1 and score the DELTA. Never count membership in buildings.all or contained_buildings.

FIX 2 — DECLARE THE PREREQUISITE, OR THE VERB IS A NO-OP (HIGH)
build_furniture requires the furniture ITEM to already exist. Chain: build_workshop(Carpenters) -> manager order ConstructBed/ConstructTable/ConstructChair/ConstructDoor -> build_furniture. Coffin nee

### Review 7 — holds=False
REFUTED on four counts; the core write sequence is close to right but the observable is broken, the confidence rating is not honest, and two required side effects are missing.

=== 1. The first observable does not compile against THIS build (HIGH confidence) ===
`dfhack.buildings.countExtentTiles(bld.room, 0)` passes the wrong type. In the shipped binary:

  $ nm -D --demangle /srv/df-bonsai/current/hack/libdfhack.so | grep countExtentTiles
  00000000008db240 T DFHack::Buildings::countExtentTiles(df::building*, int)

That is the ONLY overload — I grepped the full dynamic symbol table for `countExtentTiles` and `building_extents`, and `building_extents` has no exported identity at all. The function takes `df::building*` and dereferences `bld->room` itself.

The researcher was almost certainly misled by the shipped doc, which is STALE:
  /srv/df-bonsai/current/hack/docs/docs/dev/Lua API.txt:2385
    * "dfhack.buildings.countExtentTiles(extents,defval)"
Upstream `library/include/modules/Buildings.h` agrees with the binary, not the doc:
  `DFHACK_EXPORT int countExtentTiles(df::building *bld, int defval = -1);`
And the Lua binding is `WRAPM(Buildings, countExtentTiles)` — an auto-wrapper that derives its argument check from the C++ signature, so a `building::T_room` ref fails the `df::building` identity check and raises rather than coercing. Correct call is `countExtentTiles(bld, 0)`. (Binary + header: HIGH. Exact Lua failure mode: INFERRED.)

=== 2. Neither "observable" is an observable — both are echoes of our own writes ===
This is the more serious problem. `countExtentTiles` walks `bld->room.extents` counting non-zero bytes — the exact array the snippet just wrote. `containsTile` resolves through the file-local `getExtentTile(room, tile)`, which indexes `&room.extents[dx + dy*room.width]` off `room.x/room.y/room.width/room.height` — the exact four scalars the snippet just wrote. Both return the expected numbers even if DF ignores the repaint completely and no dwarf 

**Correction.** CORRECTED CONTRACT — set_zone_extents

API (fixes the leak, adds z, prunes stale assignments):

  -- bld: df.building_civzonest; mask: w*h booleans, row-major index = ey*w+ex
  local area = w * h
  local n_on = 0
  for i = 0, area-1 do if mask[i] then n_on = n_on + 1 end end
  if n_on == 0 then return false, 'empty extents' end   -- player cannot paint a 0-tile zone

  local old = bld.room.extents
  local ext = df.reinterpret_cast(df.building_extents_type, df.new('uint8_t', area))
  for i = 0, area-1 do ext[i] = mask[i] and 1 or 0 end

  bld.room.x, bld.room.y          = x1, y1
  bld.room.width, bld.room.height = w, h
  bld.room.extents                = ext
  if old then df.delete(old) end                        -- REQUIRED; see buildings.lua:514-517
  bld.x1, bld.y1 = x1, y1
  bld.x2, bld.y2 = x1 + w - 1, y1 + h - 1               -- bld.z unchanged; zones are single-z

  -- drop units/items now outside the footprint (notifyCivzoneModified does NOT do this)
  for i = #bld.assigned_units - 1, 0, -1 do
      local u = df.unit.find(bld.assigned_units[i])
      if not u or u.pos.z ~= bld.z
         or not dfhack.buildings.containsTile(bld, u.pos.x, u.pos.y) then
          bld.assigned_units:erase(i)
      end
  end

  dfhack.buildings.notifyCivzoneModified(bld)

FIELDS: bld building_civzonest. x1,y1 int32 upper-left (map coords). w,h int32 > 0.
mask array[w*h] of boolean, row-major, at least one true. z is implicit (bld.z); this verb
cannot move a zone between z-levels — that requires delete + recreate.

OBSERVABLES — separate the assertion from the proof:

  ASSERTION (write-echo, keep but do not call it evidence):
    dfhack.buildings.countExtentTiles(bld, 0) == n_on     -- note: bld, NOT bld.room

  PROOF (state DF/DFHack derived, that we did not write):
    1. #bld.contained_buildings before vs after, and the target building's .relations
       containing bld. These two vectors are rebuilt by notifyCivzoneModified by scanning
       world.buildings.other.IN_PLAY and

### Review 8 — holds=False
Three of the contract's four clauses are wrong, including the exact failure class you asked me to hunt for. (1) "always returns true" is contradicted by this build's own shipped doc — /srv/df-bonsai/current/hack/docs/docs/dev/Lua API.txt:2357-2359 says "Returns *false* in case of error" — while the 53.15-r2 source has every return path yield true and signals failure by raising (CHECK_NULL_POINTER), i.e. a Lua error, not false. The return value carries zero information either way. (2) The observable is not an observable: `zone.assigned_unit_id` is the field setOwner writes, read back from itself, and setOwner performs NO zone-type check — call it on a Pen/Pasture or MeetingHall and it returns true, sets assigned_unit_id, pushes onto owned_buildings, and getOwner returns the unit, while DF grants no room and no thought. All three proposed observables false-confirm on a no-op. (3) The missing side effect is real and is the flags.designated analogue: DF 51.11 moved civzone ownership to a two-field cached-index scheme (`assigned_unit_id` immediately followed by `owner_unit_cached_index` in the building_civzonest field table, confirmed in libdfhack.so), and getOwner is literally Units::get_cached_unit_by_global_id(assigned_unit_id, owner_unit_cached_index). setOwner happens to be the right call because its final act refreshes that index — but the contract doesn't know that, and setOwner also short-circuits on `if (bld->assigned_unit_id == unit_id) return true;` before touching anything, so a plain re-assign is a silent no-op that cannot repair a desynced owned_buildings. The contract omits the nil-then-unit dance that fix/ownership.lua exists to perform. It also omits every precondition (spec_sub_flag.active, required furniture in contained_buildings, non-exclusivity of assignment). Self-rating "confirmed" is not honest: API existence is HIGH, semantics and observable were inferred and are wrong.

**Correction.** WHAT ACTUALLY HOLDS (HIGH — read in shipped files on the container)

- `dfhack.buildings.setOwner(civzone, unit)` and `dfhack.buildings.getOwner(civzone)` both exist in 53.15-r2. Documented at "/srv/df-bonsai/current/hack/docs/docs/dev/Lua API.txt":2353-2359; used live in /srv/df-bonsai/current/hack/scripts/fix/ownership.lua:36-42 and /srv/df-bonsai/current/hack/lua/plugins/sort/places.lua:82.
- The four owner-bearing zone kinds ARE Bedroom / Office / DiningHall / Tomb. Best citation is fix/ownership.lua:26-31, which iterates exactly `world.buildings.other.ZONE_BEDROOM / ZONE_OFFICE / ZONE_DINING_HALL / ZONE_TOMB`.
- `zone:canUseSpouseRoom()` exists — symbol `_ZN2df8building16canUseSpouseRoomEv` in libdfhack.so. It is a method on `df::building`, not on civzone specifically.
- Field names `assigned_unit_id`, `assigned_units`, `owned_buildings` all exist (symbols `building_civzonest_fields_Extra_assigned_unit_id`, `..._assigned_units`, and `owned_buildings` in libdfhack.so).

REFUTATION 1 — the citation is misattributed
store-owned.lua never calls `dfhack.buildings.setOwner`. Its only setOwner/getOwner calls are `dfhack.items.setOwner` / `dfhack.items.getOwner` (store-owned.lua:7,337) — item ownership, a different subsystem. It does enumerate the four civzone types at store-owned.lua:232-235, so the conclusion is right by luck. Cite fix/ownership.lua instead.

REFUTATION 2 — "always returns true" (the contract's API line)
This build's shipped doc says "Replaces the owner of the civzone. If unit is *nil*, removes ownership. Returns *false* in case of error." The 53.15-r2 implementation disagrees: it opens with `CHECK_NULL_POINTER(bld);`, and both return statements yield `true`. The doc is stale; the bool is vestigial. Practical consequence for the dispatcher: a wrapper written as `if dfhack.buildings.setOwner(z,u) then ok = ok + 1 end` will report success unconditionally and will never observe a failure, while a nil/stale zone pointer raises and aborts the whole action

### Review 9 — holds=False
REFUTED. The function inventory is real; almost everything else in the contract is wrong, and the failure mode is silent.

WHAT SURVIVES (HIGH confidence, read on this build)
All named natives exist in buildingplan.plug.so: setMaterialFilter, getMaterialFilter, setMaterialMaskFilter, getMaterialMaskFilter, clearFilter, resetFilters, getAvailableItems, countAvailableItems, plus hasFilter, get/setQualityFilter, get/setHeatSafetyFilter, get/setChooseItems, getSpecials/setSpecial, getQueuePosition, getGlobalSettings, getAvailableItemsByHeat, getDescString. Note the doc comment at the top of /srv/df-bonsai/current/hack/lua/plugins/buildingplan.lua lists only 5 natives and is STALE — the real list is in the binary. get_num_filters(btype,subtype,custom) is real (buildingplan.lua:62). Arg order (btype, subtype, custom, index, mats) is right and index is 0-based (every shipped call site passes self.index-1 / idx-1).

DEFECT 1 — THE MATERIAL STRINGS ARE WRONG AND FAIL SILENTLY (fatal)
mats are NOT raw tokens. The C++ keys a cache on MaterialInfo::toString() — readable lowercase names: 'gold', 'silver', 'granite', 'pig tail cloth'. Lookup is `if (mat_cache.count(mat)) mats.emplace(...)` with NO else. So {'GOLD','SILVER'} matches nothing, raises nothing, returns nothing. Worse, it is not a no-op: the same function then does `if (!mats.size()) mask.whole = 0;` — an empty set ALSO zeroes the material mask. The proposed snippet actively clears the filter while appearing to set it. This is precisely the flags.designated class of bug: looks correct, does nothing, no diagnostic. Also undocumented in the contract: setMaterialFilter mutates the mask as a side effect, ORing in each chosen material's category bit — so the "companion" setMaterialMaskFilter is not independent, and calling it after set prunes materials that don't match the mask.

DEFECT 2 — THE SNIPPET IS INERT; IT MISSES PLACEMENT AND REGISTRATION (fatal)
setMaterialFilter writes a plugin-global config keyed by (btype,subt

**Correction.** Split the proposal into a working verb plus a validator, and retarget it at buildings that actually take raw building material.

1) NAMES: enumerate, never hardcode. Valid names are exactly the keys of getMaterialFilter, which are MaterialInfo::toString() form ('gold', 'granite', 'pig tail cloth'). The dispatcher must reject unknown names itself because the plugin will not:

local bp = require('plugins.buildingplan')
local function valid_mats(btype, subtype, custom, idx)
    local out = {}
    for name, props in pairs(bp.getMaterialFilter(btype, subtype, custom, idx)) do
        out[name] = { category = props.category, count = tonumber(props.count) }  -- both come back as STRINGS
    end
    return out
end

local function set_mats(btype, subtype, custom, idx, wanted)
    local ok_names, chosen, rejected = valid_mats(btype, subtype, custom, idx), {}, {}
    for _, m in ipairs(wanted) do
        local key = m:lower()
        if ok_names[key] then table.insert(chosen, key) else table.insert(rejected, m) end
    end
    if #chosen == 0 then return false, rejected end   -- refuse: an empty set would ZERO the mask
    bp.setMaterialFilter(btype, subtype, custom, idx, chosen)
    return true, rejected
end

2) PLACEMENT: the filter is inert without construction plus registration. Make the atomic verb place_planned_building(btype, subtype, custom, pos, mats), which sets the filter, constructs, registers, schedules, then clears:

local filters = dfhack.buildings.getFiltersByType({}, btype, subtype, custom)
local bld, err = dfhack.buildings.constructBuilding{pos=pos, type=btype, subtype=subtype, custom=custom, filters=filters}
if bld then bp.addPlannedBuilding(bld); bp.scheduleCycle() end
bp.clearFilter(btype, subtype, custom, idx)   -- filters are global and sticky; always reset

3) TARGETS: use it on buildings whose job_item is raw building material, not a pre-made furniture item. Check with dfhack.buildings.getFiltersByType and look for flags2.building_material (e.g. TradeD

### Review 10 — holds=False
WHAT SURVIVES (concede this much). The field is real and correctly named. `df.building.xml` in df-structures declares `<bitfield base-type='uint32_t' type-name='civzone_activity_flag' name='spec_sub_flag'/>` on `building_civzonest`, and `civzone_activity_flag` has exactly one meaningful bit, `active`, at bit index 3 (the other 11 are `unused_01..unused_12`). This build corroborates it: `strings libdfhack.so` has `spec_sub_flag` in the `building_civzonest` field run (next to `assigned_units`, `assigned_unit_id`, `owner_unit_cached_index`, `retained_owner`), and the `unused_02/unused_03/unused_05..unused_12` cluster sits in the same string region as the `civzone_type` enum names and the pen/pond/gather flags. Shipped code uses it both ways: /srv/df-bonsai/current/hack/scripts/entomb.lua:56 reads `building.spec_sub_flag.active`, /srv/df-bonsai/current/hack/scripts/internal/quickfort/zone.lua:132 sets it true on every zone type, :240 sets it false for the blueprint property, and the user guide documents it (/srv/df-bonsai/current/hack/docs/docs/guides/quickfort-user-guide.txt:1667, `"active" | if set to "false" then the zone is deactivated`). Player parity is real too: `df.main_hover_instruction.ZONE_SUSPEND` exists in the binary and /srv/df-bonsai/current/hack/lua/plugins/preserve-rooms.lua:118-122 lists it as a conflicting tooltip while masking the panel's pause button. So HIGH confidence on the field, the type, and the write path. Everything after that fails.

DEFECT 1 — THE SEMANTICS ARE WRONG, AND IT IS THE SAME CLASS OF BUG AS THE DIG DESIGNATION. `active` does not gate use by the assigned owner; it gates *claiming by unassigned units*. The only implementation anywhere that toggles a *live* zone is DFHack's preserve-rooms plugin (C++), and it never writes the bit alone. Every suspension is paired with an eviction: the noble path does `zone->spec_sub_flag.bits.active = false;` together with `Buildings::setOwner(zone, NULL);`. The guard around it is decisive — `if (

**Correction.** The bit is real; the contract around it is not. Split it into two verbs and fix the observable.

VERB: set_zone_active
PURPOSE: Suspend/resume a zone's availability for NEW claims. It does NOT evict a current owner and does NOT stop an existing owner using the room.
FIELDS: zone_id: int (building id, must resolve to a `building_civzonest`); active: bool.
API (HIGH confidence on fields/types; INFERRED that the write alone is sufficient for the claiming effect, since only C++ preserve-rooms does this on a live zone):
    local bld = df.building.find(zone_id)
    if not bld or not df.building_civzonest:is_instance(bld) then return false, 'not a civzone' end
    bld.spec_sub_flag.active = active   -- civzone_activity_flag, uint32, bit 3
    return true
No `notifyCivzoneModified` and no `categorize`/`uncategorize` are required for a flag-only change (those are for extent/size and location changes respectively).
OBSERVABLE (must be behavioural, measured across a tick advance, never a read-back of the written bit): with `active=false` on an UNOWNED zone, `bld.assigned_unit_id` remains -1 across N advanced ticks while at least one eligible unowned citizen exists; flipping to `active=true` lets `assigned_unit_id` become != -1 within the same window. Record `assigned_unit_id` before and after as the receipt.
CONFIDENCE: field/type/bit = HIGH. "prevents new claims" = MEDIUM (read from preserve-rooms' documented intent and its guard `if (!assigned && (active || assigned_unit_id != -1))`, not measured by us). Needs one live episode to confirm before we ship it.

VERB: set_zone_owner   (this is the verb that actually does what the proposal claimed)
PURPOSE: Assign or clear the occupant of an assignable zone (Bedroom, Office, DiningHall, Tomb).
API: `dfhack.buildings.setOwner(bld, unit_or_nil)` — documented in this build's Lua API; returns false on error. Read back with `dfhack.buildings.getOwner(bld)`.
    local bld = df.building.find(zone_id)
    local unit = unit_id and df.unit

### Review 11 — holds=False
REFUTED on four counts; the self-rating "confirmed" is not defensible.

WHAT IS ACTUALLY RIGHT (HIGH — read in shipped files):
- `dfhack.buildings.setOwner(civzone, unit)` exists. `hack/docs/docs/dev/Lua API.txt:2357`: "Replaces the owner of the civzone. If unit is *nil*, removes ownership. Returns *false* in case of error."
- `df.building.find(id)` exists (`hack/scripts/internal/emigration/unit-link-utils.lua:150`).
- `assigned_unit_id` (int32) exists on civzone (`hack/scripts/store-owned.lua:41` `civzone.assigned_unit_id`; `hack/scripts/entomb.lua:45,148,233,391`).
- `unit.owned_buildings` exists, but it is a vector of building POINTERS, not ids (`fix/ownership.lua:38` `utils.linear_index(unit.owned_buildings, zone.id, 'id')`; `unit-link-utils.lua:150` `unit.owned_buildings[i].id`).
- `setOwner(zone, nil)` is the right core primitive — canonical call site is `unit-link-utils.lua:151`.

FAILURE 1 — THE MISSING SIDE EFFECT, AND IT IS WORSE THAN THE DIG CASE: A BACKGROUND PLUGIN REVERTS THE WRITE.
Two DFHack plugins own room assignment in this build and are ON by default:
- `hack/init/dfhack.tools.init:12` → `enable preserve-rooms` (unconditional, every launch).
- `hack/scripts/internal/control-panel/registry.lua:114` → `{command='preserve-tombs', group='bugfix', mode='enable', default=true}`.
Per `hack/docs/docs/tools/preserve-rooms.txt` (features `track-missions` and `track-roles`, "This feature is enabled by default"):
- track-missions: when a citizen leaves the map, the plugin RESERVES their rooms and DISABLES the zone. The room's real state lives in the plugin's reservation table. For a DEPARTED dwarf — one of the two stated purposes — `assigned_unit_id` is ALREADY -1 while the room is still held. `setOwner(zone,nil)` is a no-op on the thing that actually holds it.
- track-roles: a zone associated with a noble role is auto-reassigned to the current role holder on the plugin's background cycle. `setOwner(nil)` is silently reverted.
Per `hack/docs/docs/tools/prese

**Correction.** CORRECTED CONTRACT — unassign_room

Field names below are HIGH confidence (read in shipped Lua) unless marked INFERRED.

FIELDS: `zone_id` (int32) — must be a `building_civzonest` whose `.type` is one of `df.civzone_type.Bedroom|Office|DiningHall|Tomb`. Reject anything else.

PREREQUISITE (do this once at episode init, not per action): neutralise the plugins that
revert room writes, so room verbs have deterministic semantics. Our `onMapLoad.init` already
runs our own `bonsai-headless-init`, which is the right place:
    preserve-rooms disable track-missions
    preserve-rooms disable track-roles
and leave `preserve-tombs` disabled (it is default=true in the control-panel registry, so
assert it is off rather than assuming). Without this, `unassign_room` is not an atomic action —
it is a suggestion that a background plugin may overturn within 100 ticks.

API:
```lua
-- unassign_room(zone_id) -> 'ok' | error code
local ROOM_TYPES = {
    [df.civzone_type.Bedroom]=true, [df.civzone_type.Office]=true,
    [df.civzone_type.DiningHall]=true, [df.civzone_type.Tomb]=true,
}

local bld = df.building.find(zone_id)
if not bld then return 'no-zone' end
if not df.building_civzonest:is_instance(bld) then return 'not-a-civzone' end
local zt = bld.type                       -- entomb.lua:44 uses .type; fix/ownership.lua:40
if not ROOM_TYPES[zt] then return 'not-an-owned-room' end  -- uses zone:getSubtype(); both work

-- 1. drop any noble-role association first, or preserve-rooms reassigns on its next cycle.
--    Skip if track-roles is disabled at init (preferred).  INFERRED: {''} is the widget's
--    'None' option value (preserve-rooms.lua option list), passed to preserve_rooms_assignToRole.
local ok, pr = pcall(require, 'plugins.preserve-rooms')
if ok and pr.preserve_rooms_assignToRole then
    pr.preserve_rooms_assignToRole({''}, bld.id)
end

-- 2. clear the owner (the only step the proposal had). Documented to return false on error.
if dfhack.buildings.setOwner(bld, nil) == fa

### Review 12 — holds=False
REFUTED. Three claims are false against DF v0.53.15 / DFHack 53.15-r2, and the "confirmed" rating is not honest — the researcher quoted docs and two call sites but never read the implementation.

WHAT IS RIGHT (credit where due, all HIGH):
- `dfhack.buildings.setOwner(civzone,unit)` exists and is Lua-exposed — /srv/df-bonsai/current/hack/docs/docs/dev/Lua API.txt:2357. `getOwner` at :2352.
- `building_civzonest.assigned_unit_id` exists in this build — symbol `_ZN2dfL48building_civzonest_fields_Extra_assigned_unit_idE` in hack/libdfhack.so. `unit.owned_buildings` exists too.
- The cited lines are real: entomb.lua:148-150 writes both sides; unit-link-utils.lua:151 frees with `setOwner(tmp, nil)`.
- Preferring setOwner over raw field writes is the correct call — more correct than the researcher realised (see #2).

1. THE ERROR CHECK IS DEAD CODE — setOwner CANNOT RETURN FALSE.
library/modules/Buildings.cpp @ tag 53.15-r2: `setOwner` contains exactly two return statements, both `return true;`. The only other exit is `CHECK_NULL_POINTER(bld)`, which raises a Lua error rather than returning false. So `if not dfhack.buildings.setOwner(bld, unit) then return 'setowner-failed' end` can never fire; the dispatcher reports success unconditionally. The doc sentence the researcher quoted ("Returns false in case of error") is STALE — `Lua API.txt` was never updated when setOwner was "updated for changes in 51.11" (hack/docs/docs/changelogs/news.txt:1387). The contract is built on a doc line the code contradicts.

2. THE MISSING SIDE EFFECT — `owner_unit_cached_index`. This is exactly the flags.designated class of bug.
Since 51.11 DF resolves civzone ownership through a CACHED VECTOR INDEX, not the raw id. The zone carries a second field `owner_unit_cached_index` — confirmed present in this build (string in hack/libdfhack.so). `getOwner` is implemented as `Units::get_cached_unit_by_global_id(bld->assigned_unit_id, bld->owner_unit_cached_index)`, and setOwner's last statement before

**Correction.** WHAT IS ACTUALLY TRUE, and the contract that survives.

VERB: assign_room_to_unit
FIELDS: `zone_id` (int32, a `building_civzonest` id), `unit_id` (int32, live citizen).
RETURNS: a status string. Never trust setOwner's bool — it is always true.

PRECONDITIONS THE CONTRACT MUST ENFORCE (the original enforces none of these):
a. subtype is ownable — exactly Bedroom / Office / DiningHall / Tomb (fix/ownership.lua:26-31). Accessor is `bld:getSubtype()`, confirmed by fix/ownership.lua:39 printing `df.civzone_type[zone:getSubtype()]`. HIGH.
b. the zone physically contains its furniture. An owned Bedroom zone with no bed inside is an owned room that does nothing. entomb.lua's GetCoffin (scripts/entomb.lua:161-171) shows the idiom: iterate `bld.contained_buildings` and `is_instance`-test. `contained_buildings` confirmed present in this build (string in libdfhack.so). HIGH for the mechanism; the type->furniture mapping is INFERRED from standard DF room rules but corroborated by gui/room-list.lua:19-24, whose `room_type_table` maps exactly building_bedst / building_tablest / building_chairst / building_coffinst — the same four, one per ownable zone type.

CORRECTED SNIPPET:

    local utils = require('utils')
    -- Exactly the four ownable civzone subtypes (fix/ownership.lua enumerates these).
    local NEEDS = {
        [df.civzone_type.Bedroom]    = df.building_bedst,
        [df.civzone_type.Office]     = df.building_chairst,
        [df.civzone_type.DiningHall] = df.building_tablest,
        [df.civzone_type.Tomb]       = df.building_coffinst,
    }

    local bld  = df.building.find(zone_id)
    local unit = df.unit.find(unit_id)
    if not bld or not unit then return 'bad-args' end
    if not df.building_civzonest:is_instance(bld) then return 'not-a-zone' end

    local want = NEEDS[bld:getSubtype()]
    if not want then return 'zone-not-ownable' end   -- setOwner will NOT catch this

    local has = false
    for _, c in ipairs(bld.contained_buildings) do
        if wan

### Review 13 — holds=False
The API skeleton is real, but the contract fails on four counts: the primary observable does not exist as a symbol, two required side effects are omitted (one of them explicitly commented in the very file cited as the source), the rest of the observable is a readback of the input, and the stated PURPOSE is unreachable from the contract as written. Self-rating "confirmed" is not honest — the snippet as printed would throw before it ever printed.

WHAT IS ACTUALLY CORRECT (HIGH — read on this build):
- The constructBuilding shape is right. `/srv/df-bonsai/current/hack/scripts/internal/quickfort/zone.lua:365-368` is the only civzone creation site in the entire shipped tree.
- `df.civzone_type` key list is correct (`/srv/df-bonsai/current/hack/lua/plugins/sort/places.lua:13-30`).
- `bld.type` really does hold the civzone_type, not building_type: `entomb.lua:44` does `building.type == df.civzone_type.Tomb`.
- `findCivzonesAt` and `notifyCivzoneModified` both exist (`hack/docs/docs/dev/Lua API.txt:2373`, `:2435`).

REFUTATION 1 — `world.buildings.other.ZONE` does not exist (HIGH).
The `building_list` enum in `hack/libdfhack.so` runs `ANY_ZONE, ACTIVITY_ZONE, ZONE_HOME, …, ZONE_DORMITORY, ZONE_DINING_HALL, …, ZONE_BEDROOM, ZONE_OFFICE, ZONE_ARCHERY_RANGE, ZONE_BARRACKS, ZONE_DUNGEON, ZONE_TOMB`. There is no bare `ZONE`. Shipped proof: `hack/scripts/fix/ownership.lua:26-31` builds its vector list from `other.ZONE_BEDROOM, other.ZONE_OFFICE, other.ZONE_DINING_HALL, other.ZONE_TOMB`. `#...other.ZONE` is a nil index. The counter must be per-type (`other.ZONE_OFFICE`) or `other.ANY_ZONE`.

REFUTATION 2 — the zone is created INACTIVE; this is the dig-designation bug again (HIGH).
`zone.lua:129-132` does, for every zone type: `ensure_keys(v.default_data, 'assign', 'spec_sub_flag').active = true` with the literal comment `-- set to active by default`. The proposal never sets `spec_sub_flag.active`. That field is load-bearing: `entomb.lua:56` skips any zone where `not building.spec

**Correction.** SPLIT THE VERB. `create_room_zone` cannot deliver "the manager can now work"; that needs three sequenced atomics: `build_furniture(chair)` -> `create_room_zone` -> `assign_room(zone_id, role)`. Make the dependency explicit in the contract rather than implied by PURPOSE.

CORRECTED create_room_zone (matches the only shipped pattern):

```lua
local preserve_rooms = require('plugins.preserve-rooms')

local function create_room_zone(zone_type, x, y, z, width, height, owner_role)
  local ztype = df.civzone_type[zone_type]
  if type(ztype) ~= 'number' then return 'bad-zone-type: '..tostring(zone_type) end

  -- (1) extents: quickfort allocates these for EVERY zone, not just ragged ones.
  --     one uint8 per tile of the bounding rect, 1 = tile is in the zone.
  local area = width * height
  local extents = df.reinterpret_cast(df.building_extents_type, df.new('uint8_t', area))
  for i = 0, area - 1 do extents[i] = 1 end

  local bld, err = dfhack.buildings.constructBuilding{
    type = df.building_type.Civzone, subtype = ztype, abstract = true,
    pos = xyz2pos(x, y, z), width = width, height = height,
    fields = { assigned_unit_id = -1,
               room = { x = x, y = y, width = width, height = height,
                        extents = extents } } }
  if not bld then return 'zone-failed: '..tostring(err) end  -- extents freed by DFHack on error

  -- (2) THE MISSING STEP: an inactive zone is allocated but ignored by the game.
  bld.spec_sub_flag.active = true

  -- (3) rebuild the civzone <-> contained-building map so the office sees its chair,
  --     even if the chair was built before the zone was painted.
  dfhack.buildings.notifyCivzoneModified(bld)

  -- (4) ownership is two-way; setOwner maintains both sides.
  --     assignToRole is better for nobles: it re-points the zone automatically
  --     when a different unit takes the role.
  if owner_role then preserve_rooms.assignToRole(owner_role, bld) end

  return bld.id
end
```

`preserve-rooms.plug.so` is pr

### Review 14 — holds=False
REFUTED. The fields exist, but the central justification is false, the snippet omits two side effects the shipped flow performs, and the "observable" is a read-back of the byte we wrote.

WHAT IS ACTUALLY CONFIRMED (HIGH — read on this build)
- `/srv/df-bonsai/current/hack/scripts/internal/emigration/unit-link-utils.lua` exists; `unassignMayor` is at lines 5-54 and the snippet is a near-verbatim copy of lines 11-53.
- `entity_position_assignment` fields `histfig`, `histfig2`, `position_id`, `position_vector_idx`, `squad_id` are all in this build's metadata (`strings hack/libdfhack.so`, offsets ~89443-89460). df-structures df.entity.xml:1016-1041 gives types: `histfig` = `holder_hfid`, `histfig2` = `last_holder_hfid`, `position_vector_idx` = `position_cache_index` (init -1).
- `historical_entity.assignments_by_type` is real and is `static-array[entity_position_responsibility] of stl-vector<entity_position_assignment*>` (df.entity.xml:1738-1740), so `v[i].id == asg.id` is type-valid. `entity_position.responsibilities` is `static-array of bool` indexed by the same enum (df.entity.xml:984) — not a bitfield, so `ipairs`/`[r]` line up.
- `dfhack.units.getUnitByNobleRole(role_name)` exists: symbol `_ZN6DFHack5Units18getUnitByNobleRoleE...` in libdfhack.so and documented at `hack/docs/docs/dev/Lua API.txt:1645`.
So the *mechanical* parts are not invented. Everything below is why the contract still fails.

R1 — THE CITED AUTHORITY EXPLICITLY REFUSES THIS OPERATION (HIGH)
`unassignMayor` is gated on `pos.position.flags.ELECTED` (unit-link-utils.lua:10) and is only ever reached via `removeHistFigFromEntity(hf, ent, removeMayor)` with `removeMayor = (adminType == IS_ELECTED)` (emigrate-nobles.lua:293-294). For the appointed-administrator case — manager, bookkeeper, broker, i.e. the exact motivating example — DFHack aborts:
    emigrate-nobles.lua:287-291
    adminType = getAdminType(noble, fortEnt)
    if adminType == AdminType.IS_ADMIN then
        print("! "..nobleName.." is 

**Correction.** WHAT IS ACTUALLY TRUE, AND WHAT TO SHIP INSTEAD

1. Scope the verb honestly. There is no maintained DFHack precedent for vacating an appointed position; the only shipped path handles the ELECTED mayor during emigration and explicitly declines administrators. Ship `vacate_position` restricted to an allow-list of APPOINTED fort positions with no symbol, no mandate power and no squad — MANAGER, BOOKKEEPER, BROKER — and reject MAYOR, MONARCH, BARON/COUNT/DUKE, CAPTAIN_OF_THE_GUARD and any position with `flags.ELECTED`, `mandate_max > 0`, `demand_max > 0`, or `assignment.squad_id ~= -1`. That covers the stated need (replace a dead/soldiering manager) and stays inside verified ground.

2. Resolve the position over BOTH entities, and normalise the code, exactly as Units.cpp does — `plotinfo.civ_id` then `plotinfo.group_id` (`plotinfo.main.fortress_entity`), with `position_code:upper()`. Return distinct results: `unknown-position` (no such code on either entity) vs `already-vacant` (found, `histfig == -1`) vs `refused-<reason>` vs `ok`. Never collapse "not found" into "already vacant".

3. Keep the link surgery, add the two omitted steps, and mirror faithfully:
   - set `asg.histfig = -1` AND `asg.histfig2 = -1` (unit-link-utils.lua:11-12) unless you can justify otherwise in writing;
   - swap `histfig_entity_link_positionst` -> `histfig_entity_link_former_positionst` and emit `history_event_remove_hf_entity_linkst` (as proposed — this part is faithful);
   - THEN `unassignSymbols(asg.id, entity, site)` — call the shipped function, do not reimplement it:
       local ulu = reqscript('internal/emigration/unit-link-utils')
       ulu.unassignSymbols(asg.id, ent, dfhack.world.getCurrentSite())
     It is `--@module = true` (line 1) so `reqscript` works, and this is the DFHack-maintained code the proposal should actually have cited.
   - THEN remove mandates owned by the ex-holder (pattern at emigrate-nobles.lua:83-92) if the position had any.
   Drop the `assignments_by_type` 

### Review 15 — holds=False
REFUTED. The API *shape* is right (it is a faithful copy of quickfort's create_zone), but the contract is wrong on preconditions, silently produces inert zones for 5 of its 18 kinds, contains a save-corrupting field, and its observable cannot distinguish a working room from an empty rectangle. "confirmed" is not an honest rating.

WHAT IS ACTUALLY CORRECT (HIGH — read in shipped code)
- The constructBuilding call is verbatim quickfort's create_zone, /srv/df-bonsai/current/hack/scripts/internal/quickfort/zone.lua:355-386.
- abstract=true really is mandatory. /srv/df-bonsai/current/hack/lua/dfhack/buildings.lua:487-493 raises "one of items, filters or abstract is required" when getFiltersByType returns nil, and building_inputs (buildings.lua:34-...) has no df.building_type.Civzone key. Confirmed by grep: no `building_type.Civzone` anywhere in buildings.lua.
- The extents idiom, row-major order and 1/0 values match make_extents, /srv/df-bonsai/current/hack/scripts/internal/quickfort/building.lua:565-581 (index = (ey-1)*w + (ex-1), value 1 = in zone).
- All 18 civzone_type names exist: every one is dereferenced as df.civzone_type.X in zone_db_raw, zone.lua:100-127.
- The hidden-tile rule matches is_valid_zone_tile, zone.lua:73-75.
- The ZONE_* vector names exist in THIS build. I pulled the buildings_other_id key table out of .rodata in /srv/df-bonsai/current/hack/libdfhack.so (contiguous run, file offsets 10525243 ANY_ZONE → 10527065 LOCATION_ASSIGNED): ZONE_BEDROOM, ZONE_OFFICE, ZONE_DINING_HALL, ZONE_TOMB, ZONE_DORMITORY, ZONE_BARRACKS, ZONE_MEETING_HALL are all there, and /srv/df-bonsai/current/hack/scripts/fix/ownership.lua:126-131 indexes four of them on civzones.

DEFECT 1 — THE flags.designated-CLASS BUG YOU ASKED ME TO HUNT. The contract never writes zone_settings, so for 5 kinds constructBuilding succeeds, the counter increments, and the zone does nothing. quickfort sets these as *defaults for every zone it creates* (zone.lua:100-133):
  PlantGathering → zone_s

**Correction.** PREFER THE SHIPPED SERIALISABLE FORMAT. This build ships quickfort's programmatic API — do not hand-roll create_zone.

  local quickfort = reqscript('quickfort')   -- /srv/df-bonsai/current/hack/scripts/quickfort.lua:43-56
  local stats = quickfort.apply_blueprint{
      mode='zone', pos={x=x1,y=y1,z=z},
      data={[0]={[0]={[0]='b{name="Urist bedroom"}'}}},   -- {[z]={[y]={[x]=cellText}}}, or a plain string
  }

data is normalised by /srv/df-bonsai/current/hack/scripts/internal/quickfort/api.lua normalize_data; cell text uses `#dig`-style expansion so one cell can paint the whole rectangle. The zone mini-language (zone.lua:100-256) already encodes every setting the proposal omits:
  kinds: m MeetingHall, b Bedroom, h DiningHall, n Pen, p Pit/Pond, w WaterSource, j Dungeon, f FishingArea, s SandCollection, o Office, D Dormitory, B Barracks, a ArcheryRange, d Dump, t AnimalTraining, T Tomb, g PlantGathering, c ClayCollection
  props: name=, active=false, assigned_unit=<role code>, pond=true, pick_trees/pick_shrubs/gather_fallen=false, shoot_from=west|east|north|south, pets=true, citizens=false, location=tavern|temple|hospital|library|guildhall, allow=visitors|residents|citizens|members, profession=<df.profession key>, desired_goblets/instruments/splints/thread/cloth/crutches/powder/buckets/soap/paper=<int>
It applies crop_to_bounds, the hidden-tile filter, the per-kind zone_settings defaults and full location creation for you, and RETURNS A STATS TABLE — zone_designated, zone_tiles, zone_occupied, out_of_bounds, invalid_keys — which is a far better action result than anything in the proposal. (HIGH that the API and these params exist; INFERRED that every property string I did not individually read parses identically at 53.15-r2 — I read the pit/pond, gather, archery, tomb and location parsers.)

IF YOU STILL WANT A RAW VERB, THIS IS THE CORRECTED CONTRACT.

VERB create_zone
FIELDS
  kind    string, validated against an explicit 18-entry table (never trust df.civzone

### Review 16 — holds=False
The function exists and the arity is right, but the contract is wrong on the three things that matter: the snippet has no effect at all unless the building is registered with buildingplan (and the order is load-bearing), the "observable" is half write-back and half literally incapable of reading the top tier it claims to target, and the stated invariant is misattributed. "confirmed" is not an honest rating.

WHAT IS ACTUALLY CONFIRMED (I read it in this build)
- `setQualityFilter` / `getQualityFilter` exist. Mangled symbol in /srv/df-bonsai/current/hack/plugins/buildingplan.plug.so: `_ZL16setQualityFilterRN6DFHack13color_ostreamEN2df5enums13building_type13building_typeEsiiiii` = (btype enum, int16 subtype, int32 custom, int32 index, int32 decorated, int32 min_quality, int32 max_quality). 7 game args, matching the proposal. Shipped Lua callers: hack/lua/plugins/buildingplan/filterselection.lua:312 (get) and :416/:428/:440 (set). Version string in libdfhack.so is `53.15-r2-0-g425442d4`.
- `getQualityFilter` returns a table with integer keys `decorated`, `min_quality`, `max_quality` (filterselection.lua:313-315).
- `df.item_quality` is 0..6 with Artifact=6; the shipped widget lists exactly those 7 labels (filterselection.lua:160-197, RangeSlider num_stops=7).
- `item:getQuality()` exists (hack/scripts/combine.lua:207, sort/items.lua:28).

DEFECT 1 — MISSING SIDE EFFECT, exactly the flags.designated class. `setQualityFilter` mutates `DefaultItemFilters`, a plugin-global map keyed by BuildingTypeKey. It never touches a building. The value reaches a building exactly once, at plan-registration time: `PlannedBuilding pb(out, bld, get_heat_safety_filter(key), get_item_filters(out, key));` inside `addPlannedBuilding`. Our dispatcher at D:\side_projects\bonsai_dwarf_fortress\lab_agent\bonsai_lab_agent\dfhack\bonsai-apply-actions.lua:130 and :149 calls `dfhack.buildings.constructBuilding` and never calls `addPlannedBuilding` — so as written this verb is a no-op in our pipeline.

**Correction.** Replace the single-call verb with a compound verb that owns the whole lifecycle, gate it on the improvability precondition, and observe the job rather than the config.

```lua
local bp = require('plugins.buildingplan')
local BT, SUB, CUS, IDX = df.building_type.Bed, -1, -1, 0

-- precondition 1: the filter slot exists (setQualityFilter is a silent no-op otherwise)
if IDX >= bp.get_num_filters(BT, SUB, CUS) then return false, 'no such filter slot' end
-- precondition 2: this filter's items can carry a quality at all. Mirror
-- filterselection.lua:35-44 - reject building_material / WOOD / BLOCKS / BAR / BOULDER,
-- else min_quality >= 1 produces a job no item can ever satisfy.
local f = dfhack.buildings.getFiltersByType({}, BT, SUB, CUS)[IDX + 1]
if (f.flags2 and f.flags2.building_material)
   or f.item_type == df.item_type.WOOD  or f.item_type == df.item_type.BLOCKS
   or f.item_type == df.item_type.BAR   or f.item_type == df.item_type.BOULDER then
    return false, 'quality is not applicable to this filter'
end

-- 1. set the band BEFORE the building exists: defaults are snapshotted at plan time
bp.setQualityFilter(BT, SUB, CUS, IDX, decorated and 1 or 0, min_q, max_q)
-- 2. place, register, kick the matcher (CYCLE_TICKS = 599, twice a game day, otherwise)
local bld = dfhack.buildings.constructBuilding{type=BT, subtype=SUB, custom=CUS, pos=pos}
if bld and bp.isPlannableBuilding(BT, SUB, CUS) then
    bp.addPlannedBuilding(bld)   -- snapshots filters AND sets bld.jobs[0].flags.suspend
    bp.scheduleCycle()
end
-- 3. restore the global default, or every later Bed inherits this band silently
bp.clearFilter(BT, SUB, CUS, IDX)
```

OBSERVABLES that are actually observables:
- satisfiable: `bld.jobs[0].job_items.elements[IDX].quantity` falls to 0 and `bld.jobs[0].flags.suspend` clears. Both confirmed idioms - hack/scripts/build-now.lua:69-77 reads `job.job_items.elements` and tests `quantity > 0`, with the shipped comment that buildingplan deliberately leaves 0-quantity 

### Review 17 — holds=False
REFUTED on three independent counts, the first fatal.

**1. `nil`/`-1` does NOT clear a reservation — it means "the zone the player currently has selected in the UI".** This is the core error. Disassembly of `/srv/df-bonsai/current/hack/plugins/preserve-rooms.plug.so`:
- `0x18344` `luaL_checkinteger(L, 2)` reads zone_id
- `0x1834b` `cmp $0xffffffff,%eax; je 0x18560`
- `0x18560` -> `0x18568 call DFHack::Gui::getSelectedCivZone(color_ostream&, bool)` with `true`
- `0x18570` if it returns NULL -> `0x184df` -> `xor %eax,%eax; ret` (returns 0 Lua values)

`nm -D` confirms `DFHack::Gui::getSelectedCivZone` is an undefined import of this .so — it would not be linked if -1 were a "clear" sentinel. Upstream `plugins/preserve-rooms.cpp` at tag 53.15-r2 corroborates verbatim: `auto zone = zone_id == -1 ? Gui::getSelectedCivZone(*out, true) : ...`.

Consequence for us: headless, with no zone under the cursor, `pr.assignToRole(code, nil)` is a **silent no-op that raises nothing and returns nothing**. The proposed contract would have the dispatcher report a successful clear while the binding remains intact — a silent divergence between the agent's world-model and the game. This is precisely the `flags.designated` failure class the brief warned about.

The researcher's own cited file contradicts them at `preserve-rooms.lua:156-159`: the overlay's "None" option is `value={''}` and calls `preserve_rooms_assignToRole(group_codes, -1)`. The `-1` there is *not* the clear — it is "the zone I have open". The **empty code string is the clear.** C++ guard: `if (group_codes.empty() || group_codes[0] == "")`, matching the disassembly at `0x18441` (`test %eax,%eax` on `strlen(codes[0])`).

**2. The observable is not an observable — it is the value we just wrote.** `stats.nobles` is literally `noble_zones.size()`, and `noble_zones` is the plugin's own `zone id -> position code` hashmap that `assignToRole` writes at `0x185b0`. Reading it back proves only that a C++ `std::unordered_map::operator

**Correction.** CORRECTED CONTRACT — `reserve_room_for_role`

Preconditions (state explicitly; all HIGH confidence):
- Plugin must be enabled. `hack/init/dfhack.tools.init:12` contains `enable preserve-rooms`, so it is on by default — but only if our headless harness actually runs the tools init. If it does not, `plugin_onupdate` never fires and role-following silently never happens.
- Feature `track-roles` must be on (default enabled per shipped docs). Check via `select(1, preserve_rooms_getState())['track-roles']`.
- `code_lookup` is populated only by the SC_MAP_LOADED handler registered when the Lua module is loaded. `overlay.lua:315-319` eagerly `require`s every `plugins.<name>` module at overlay init, so in a normal boot this is populated before map load. If our harness disables the overlay system, `code_lookup` is `{}` and every call fails. Guard with `next(pr.code_lookup) ~= nil`.

FIELDS:
- `position_code` (string, case-insensitive, lowercased by the wrapper). Must be a key of `code_lookup`. Validate BEFORE dispatch.
- `zone_id` (int32). Must be the building id of a `building_civzonest`. **There is no nil/-1 clear** — `-1` means "currently selected zone in the UI" and is unusable headless.
- Clearing is a distinct code path, not a null zone_id.

```lua
local pr = require('plugins.preserve-rooms')

-- returns ok, err
local function reserve_room_for_role(position_code, zone_id)
    local bld = df.building.find(zone_id)
    if not bld or not df.building_civzonest:is_instance(bld) then
        return false, ('not a civzone: %s'):format(tostring(zone_id))
    end

    if position_code == nil or position_code == '' then
        -- CLEAR. Must bypass pr.assignToRole: '' is not a key in code_lookup,
        -- so the wrapper would printerr and then throw from luaL_checktype.
        pr.preserve_rooms_assignToRole({''}, zone_id)
        pr.preserve_rooms_cycle()          -- clear path does NOT cycle itself
        return true
    end

    local group_codes = pr.code_lookup[position_

### Review 18 — holds=False
The API call is real and correctly typed, but the contract fails on three counts: its OBSERVABLE is provably false, it omits a side effect that defeats the verb's own stated PURPOSE, and its lookup key cannot address MILITIA_CAPTAIN — one of the three positions it claims to cover. Authoritative source is the shipped doc on the container, /srv/df-bonsai/current/hack/docs/docs/dev/Lua API.txt lines 1919-1945, which the researcher would have had to open to find getSquadName anyway; the sentence that breaks their observable is two lines above it.

**Correction.** ## What is confirmed correct (HIGH — read in this build)

- `dfhack.military.makeSquad(assignment_id)` exists and IS Lua-exposed. `_ZN6DFHack8Military9makeSquadEi` is exported from `/srv/df-bonsai/current/hack/libdfhack.so`; the name appears in the `dfhack_military_module` Lua registration table (`_ZL22dfhack_military_module`) alongside `addToSquad`/`removeFromSquad`/`getSquadName`/`updateRoomAssignments`; and it is documented at `Lua API.txt:1921`. The sibling signatures are exactly as claimed.
- It really does take an `entity_position_assignment` **id** (not a vector index) — stated verbatim in the shipped doc.
- `entity_position_assignment.squad_id`, `.histfig`, `.histfig2`, `.flags` all exist (binary has `entity_position_assignment_fields_Extra_squad_id` etc.).
- `positions.own` / `positions.assignments` / `p.code` / `a.position_id` are the right paths (used by `/srv/df-bonsai/current/hack/scripts/make-monarch.lua` and `exportlegends.lua`).
- `squad_size`, `leader_position`, `leader_assignment`, `uniform_priority`, `squad_next_id`, `alias`, `occupant` all exist in this build.

## Refutation 1 — the OBSERVABLE is false. A fresh squad has no name.

Shipped doc, verbatim: *"Note: This function does not name the squad. Consider setting a nickname (under `squad.name.nickname`), and/or filling out the `language_name` object at `squad.name`."*

`makeSquad` builds a blank `df::language_name` (type `Squad`, all 7 word slots `-1`, all parts of speech `Noun`) and never sets `alias`. `getSquadName` returns `alias` when `alias.size() > 0`, otherwise `translateName(&squad->name, true)` — which on a wordless name renders nothing. So the proposed observable `getSquadName(squad_id) returns a name` returns `""`. It does not merely fail to prove success; it reads as failure. Naming is a required step of the contract, and only *then* is the name an observable.

## Refutation 2 — the missing side effect (the flags.designated class of bug)

`makeSquad` creates the squad with `squad_s

### Review 19 — holds=False
The READ path is largely right, but the contract fails on the two things it was asked to get right: its OBSERVABLE is a tautology, and it cannot express the one fact it exists to expose ("MANAGER is vacant"). Self-rating "confirmed" is not honest — the headline observable was never testable as written.

WHAT I CONFIRMED (HIGH — read in shipped code on the container)
- `df.global.plotinfo.main.fortress_entity`: real, used by /srv/df-bonsai/current/hack/scripts/gui/choose-weapons.lua:21, emigration.lua:53, modtools/extra-gamelog.lua:35. The `group_id` alias is real: gui/extended-status.lua:39.
- `positions.own` / `positions.assignments`, `assignment.id/histfig/histfig2/position_id/squad_id`: real (make-monarch.lua, fix/symbol-unstick.lua:29, internal/emigration/unit-link-utils.lua).
- `position.flags.ELECTED`: real — unit-link-utils.lua uses `pos.position.flags.ELECTED`; emigrate-nobles.lua also uses `IS_LAW_MAKER`, `RULES_FROM_LOCATION`.
- `required_office/bedroom/dining/tomb`: real — summed as `required_value` in /srv/df-bonsai/current/hack/lua/plugins/preserve-rooms.lua:~305. Types per df-structures: all int32; `requires_population` int16; `precedence` int32 (init 30001).
- `assignments_by_type` on the entity (not under `positions`), `index-enum='entity_position_responsibility'`. MANAGE_PRODUCTION and ACCOUNTING are correct: entity_default.txt:642 `[RESPONSIBILITY:MANAGE_PRODUCTION]` on MANAGER, :682 `[RESPONSIBILITY:ACCOUNTING]` on BOOKKEEPER.
- `plotinfo.nobles.manager_cooldown` / `bookkeeper_cooldown`: real. Both strings are in libdfhack.so, and df-structures puts them in `plotinfo_positionst`, attached as `<compound type-name='plotinfo_positionst' name='nobles'/>`. Zero uses anywhere in hack/, so untested in practice.
- All three C++ symbols exist (`nm -D` on libdfhack.so): `Units::getNoblePositions` (unit and histfig overloads), `getUnitByNobleRole`, `getUnitsByNobleRole`. Case-insensitive confirmed: `get_noble_position_id` does `toUpper_cp437(noble)`.

DEFECT

**Correction.** ACCEPT the read path with fixes; REJECT the observable outright.

1) Invert the loop so vacancy is representable. Outer loop over `positions.own`, left-join `assignments` — and emit `exists`/`vacant` as distinct facts:

```lua
local ent = df.global.plotinfo.main.fortress_entity
local asg_by_pos = {}   -- position_id -> { {a=assignment, aidx=i}, ... }
for i, a in ipairs(ent.positions.assignments) do          -- ipairs is 0-based on DFHack vectors
  local t = asg_by_pos[a.position_id]; if not t then t = {}; asg_by_pos[a.position_id] = t end
  t[#t+1] = {a = a, aidx = i}
end
for pidx, p in ipairs(ent.positions.own) do
  local slots = asg_by_pos[p.id]
  if not slots then
    print(('POS %s id=%d pidx=%d NO_ASSIGNMENT_ROW'):format(p.code, p.id, pidx))
  else
    for _, s in ipairs(slots) do
      print(('POS %s id=%d aid=%d aidx=%d hf=%d prev_hf=%d vacant=%s ' ..
             'req_office=%d req_bed=%d req_dine=%d req_tomb=%d pop=%d num=%d prec=%d elected=%s'):format(
        p.code, p.id, s.a.id, s.aidx, s.a.histfig, s.a.histfig2, tostring(s.a.histfig == -1),
        p.required_office, p.required_bedroom, p.required_dining, p.required_tomb,
        p.requires_population, p.number, p.precedence, tostring(p.flags.ELECTED)))
      for _, ap in ipairs(p.appointed_by) do print('   appointed_by_position_id', ap) end
    end
  end
end
-- three independent views; print all three, they can disagree after a partial write
print('held_MANAGE_PRODUCTION', #ent.assignments_by_type.MANAGE_PRODUCTION)
print('held_ACCOUNTING',        #ent.assignments_by_type.ACCOUNTING)
local u = dfhack.units.getUnitByNobleRole('MANAGER')     -- reads assignment.histfig
print('byRole', u and u.id or -1)
print('byLinks', u and (dfhack.units.getNoblePositions(u) ~= nil) or false)  -- reads hf.entity_links
```

`p.flags.ELECTED` HIGH (unit-link-utils.lua). `p.appointed_by` HIGH (df-structures `<stl-vector type-name='int32_t' name='appointed_by'/>`); that it holds position ids of the appointing positions is 

### Review 20 — holds=False
The two API calls exist and the setOwner-then-deconstruct ORDER is right, but the contract omits the one guard the shipped code says is mandatory (it can crash DF), omits the type guard every shipped call site uses, ignores both documented return values, and two of its three observables do not observe anything.

WHAT IS ACTUALLY CONFIRMED (HIGH — read in this build)
- `/srv/df-bonsai/current/hack/docs/docs/dev/Lua API.txt:2357` — `dfhack.buildings.setOwner(civzone,unit)` "Replaces the owner of the civzone. If unit is nil, removes ownership. Returns false in case of error." Exists, takes a civzone, nil clears.
- `Lua API.txt:2431-2433` — `dfhack.buildings.deconstruct(building)` "Destroys the building, OR QUEUES A DECONSTRUCTION JOB. Returns true if the building was destroyed and deallocated immediately."
- `Lua API.txt:2373` — `dfhack.buildings.findCivzonesAt(pos)` exists, "returns a lua sequence of those that touch the given tile, or nil if none".
- `df.building.find(id)` does resolve civzones: `hack/lua/plugins/zone.lua:991` and `hack/scripts/internal/emigration/unit-link-utils.lua:150` do exactly that.
- The setOwner-first ordering matches shipped teardown at `unit-link-utils.lua:147-152` (`removeUnitAssociations` loops `unit.owned_buildings` calling `setOwner(tmp,nil)`). That part of the proposal is correct and worth keeping — `unit.owned_buildings` holds building POINTERS (`unit-link-utils.lua:150` dereferences `.id`; `fix/ownership.lua:38` does `linear_index(unit.owned_buildings, zone.id, 'id')`), so deallocating first would leave a dangling pointer.

DEFECT 1 — CRASH. THE FLAGS.DESIGNATED-CLASS OMISSION.
`hack/scripts/internal/quickfort/zone.lua:449-466`:
    -- ensure we don't delete the currently selected zone, which causes crashes.
    local selected_zone = dfhack.gui.getSelectedCivZone(true)
    ...
    if activity_zone == selected_zone then
        dfhack.printerr('cannot remove actively selected zone.')
    else
        dfhack.buildings.deconstruct(activ

**Correction.** CORRECTED CONTRACT

VERB: remove_room_zone
FIELDS: `building_id` (int32) — rename from `zone_id`; it is a `world.buildings.all` id shared with workshops and stockpiles, not a separate zone id space.
RETURNS (string, one of): ok | no-zone | not-a-zone | is-location | selected | owner-stuck | queued

PREFER FIRST: a `suspend_room_zone` verb that sets `bld.spec_sub_flag.active = false` (`quickfort/zone.lua:132,239-241`). It is reversible, cannot crash, and since civzones overlap it solves the stated problem without destroying anything. Make removal the second-choice verb.

```lua
-- remove_room_zone(building_id)
local function remove_room_zone(building_id)
    local bld = df.building.find(building_id)
    if not bld then return 'no-zone' end
    -- every shipped call site pairs find() with this guard (zone.lua:992, dwarfvet.lua:119,
    -- entomb.lua:44). Without it a mistyped id deconstructs a workshop instead.
    if not df.building_civzonest:is_instance(bld) then return 'not-a-zone' end
    -- temples/taverns/hospitals also have a site-level record (sort/places.lua:88-92)
    if bld.location_id ~= -1 then return 'is-location' end

    -- Deleting the zone the UI currently points at CRASHES DF. quickfort guards exactly
    -- here (internal/quickfort/zone.lua:449); the zone plugin dereferences cur_bld
    -- unguarded at zone.lua:961/988/1025.
    local ci = df.global.game.main_interface.civzone
    if dfhack.gui.getSelectedCivZone(true) == bld then return 'selected' end
    if ci.cur_bld and ci.cur_bld.id == building_id then return 'selected' end

    -- capture PRE-state so the observable is a comparison, not a read-back
    local owner = dfhack.buildings.getOwner(bld)
    local owner_id = owner and owner.id or -1

    -- drop ownership BEFORE dealloc: unit.owned_buildings holds building POINTERS
    -- (unit-link-utils.lua:150), so a surviving entry dangles after deconstruct.
    if owner and dfhack.buildings.setOwner(bld, nil) == false then return 'owner-stuck' e
