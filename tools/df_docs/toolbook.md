# The toolbook

Every verb the agent can dispatch today: what it does, what it refuses and why, what was
measured rather than assumed, and what is still unknown about it.

The organising principle is that **in Dwarf Fortress, through DFHack, almost every failure
is silent.** A write succeeds, a building appears, a job is queued, a count goes up — and
nothing happens, for a reason nobody is told. Every entry below therefore has a
*refuses* section, and most of the measurements exist because a verb once reported
success while doing nothing.

Batteries that keep these honest, both run through the real `bonsai-apply-actions` entry
point on a live fort:

* `bonsai-toolcheck` — one case per verb plus its refusal path (19/19)
* `bonsai-ordercheck` — the order machinery in depth (27/27)

Probes: `bonsai-digstat`, `bonsai-digwhy`, `bonsai-dumporders`, `bonsai-mgrdiff`,
`bonsai-plotdump`, `bonsai-entdump`.

---

## advance

Let the fort run. The only verb that changes nothing by itself.

**Measured, and it matters more than the verb does.** The advance harness used to clear
`world.status.popups` and reset `status.flags.DID_ANNOUNCE` on **every graphic frame**.
DF's fort-level services ride on that machinery, so the fort could not receive migrants
or announcements at all. Our pinned fort sat at 7 citizens across 48,000 ticks with zero
announcements. Clearing popups every ~20 seconds instead:

    citizens        7 → 15 → 18       "Some migrants have arrived."
    announcements   0 → 59            seasons turning, the outpost liaison
    throughput      ~5,000 → ~15,000 ticks per chunk, and it stopped stalling

Every episode measured before that ran in a fort that could not grow. The heartbeat
cannot simply be removed: a modal popup freezes the sim, and plain `pause_state = false`
advanced a fort by ONE tick in four minutes. The cadence has to be coarse enough to leave
the event system alive and frequent enough to unstick the sim. `bonsai-run` does this.

**Still unknown:** the right cadence. 500–2000 frames works; nothing has been swept.

---

## set_labor

Turn a labour on or off for every citizen at once.

**Refuses:** an unrecognised `df.unit_labor` name changes nothing.

**Measured:** `BREWER` off → on flips all 19 citizens and back to 0.

**The thing that surprises people.** Having the labour is not the same as being able to
do the work. On the test fort, 23 citizens carried `MINE` and the fort still dug about
five tiles per 12,000 ticks, because mining needs a **pick** and the fort has three, two
of them lying on the ground. `set_labor MINE true` raises the ceiling to the number of
picks, not to the number of dwarves. The same shape applies to `CUTWOOD` (axes) and
`HUNT` (crossbows) — `EQUIPPED_LABORS` in the catalog exists to let the gate explain
this.

**Still unknown:** nothing here is per-dwarf. A player narrows labours to individuals;
this is a blunt fort-wide switch, and `set_dwarf_labor` is still planned.

---

## designate_dig

Cut a staircase down from a pinned origin and carve a chamber off each landing.

**Refuses:** nothing outright — it designates what it can and reports the count.

### Three defects, each of which produced zero excavated tiles

**1. Designating sealed rock.** The original version stamped dig flags on a 5×5×13 block
straight down from a dwarf standing on the surface. The top layer is open air, where a
dig flag is a no-op, and everything below is sealed rock nobody can walk to. A live
ten-day episode excavated exactly zero tiles however many were "designated". Digging in
DF needs **reachability**: every tile must connect to one already reachable.

**2. Setting the tile flag is not enough.** DF only rescans blocks flagged as carrying
new designations. Writing designations through DFHack without
`block.flags.designated = true` produced a perfectly valid staircase that generated ZERO
dig jobs — measured 11 tiles marked, 0 jobs, 0 rock removed over 3,000 ticks, while
`dig-now` on the same designations excavated 35 tiles immediately.

**3. The origin moved.** Citizen[1] wanders, so pinning to its live position started a
fresh one-tile shaft on every call (observed 96,91 then 95,98) — orphaned designations
that connect to nothing. Pinning it in a Lua global fixed that only until the next
reload: the global is per DF process, so after a save/load the origin re-pinned to
wherever citizen[1] stood and the fort started a **second** orphan shaft, stranding the
first one's designations. Measured on a reloaded year-3 fort: shaft head 73,44 while
every outstanding dig job sat around 104,83. It now **recovers the origin from the map**
— if the fort has a carved stairway, that is the shaft — which is in the save and
survives reloads. Verified: clearing the process pin re-pinned to 104,83,49, the original.

### It carves a chamber, not a corridor

It used to cut four one-tile arms at radii 1..3 off each landing. Connected, diggable and
useless: nothing needing floor area ever fits, which is why `build_farm_plot 3 3` refused
while the fort had plenty of dug tiles, every one a single tile wide. It now carves a
solid `len × wide` room (default 4×3) hanging off the shaft, its first column adjacent to
the stair so every tile stays reachable, rotating sides on successive calls so the fort
grows instead of re-designating.

### Reading the state without fooling yourself

Two probe mistakes, both of which made a working fort look broken:

* **`reachable = false` on an undug wall is normal**, not a diagnosis. You cannot walk
  into rock. What matters is whether the tile above or beside it can be reached, which is
  what the staircase provides.
* **A designation that has become a job reads `dig = No`** while the tile is still a wall,
  and a probe matching only job names containing `Dig` misses the shaft entirely, because
  a staircase is cut by `CarveDownwardStaircase` and `CarveUpDownStaircase`. Counting
  designations alone made a fort that was busily digging look stalled at a fixed number
  for four rounds running.

Read together they produced a confident wrong conclusion — "digging has stopped" — when
the shaft was in fact carved to z=48 and cutting z=47.

### Order matters, and DF is right about it

Tiles one level down are **unreachable until the staircase above them is carved**, and DF
says so plainly — `reachable=false` on every one. So a fresh batch of designations looks
inert for a while. That is not a bug, and chasing it produced a **refuted** hypothesis
worth recording: every pick on our fort carries `item.flags.foreign`, another
civilisation's property, which dwarves will not claim. It looked like a complete
explanation for dig jobs that never get a worker. Clearing it changed nothing — 14 dig
jobs, 23 miners, still zero workers. `foreign` is not even abnormal: the hand-played fort
is 13% foreign items, which is what a few years of caravans looks like.

### Where the soil is

A chamber below the soil grows nothing without being muddied first. Measured on the test
fort around the shaft head:

    z=49  surface: GRASS, SOIL, STONE, open air
    z=48  SOIL (and a POOL)
    z=47  SOIL
    z=46  SOIL
    z=45  SOIL
    z=44  MINERAL / STONE  ← soil ends
    below rock

Chambers are cut at `oz-1` downwards, so the first few landings are the farmable ones.

**Still unknown:** throughput is dominated by pick count, and nothing balances the
chamber size against the dig budget.

---

## create_stockpile

Place a 2×2 stockpile on a ring around the wagon.

**Refuses:** nothing at the verb level — the count is clamped to 1..8 at the gate and the
verb places what it can. The one thing it will not do is claim a placement that did not
happen: the count only rises when `constructBuilding` returns a building.

**Measured:** 0 → 1 buildings of type Stockpile.

**It walks the ring until a placement takes**, the same way `build_workshop` does. A
single attempt worked on an empty embark and silently placed nothing once the ring
filled: measured on a fort with three stockpiles, `create_stockpile 1` reported 3 → 3.

**Still unknown, and it is a real gap.** It accepts the default everything. A player's
first act is to NARROW it — the guide removes stone and wood so bulk goods cannot crowd
out perishables. `configure_stockpile` is still planned, so the agent can make a pile but
not make it useful.

---

## build_workshop

Build a workshop on a ring around the wagon.

**Refuses:** an unknown `df.workshop_type` name. It used to fall back to Carpenters — the
same silent-substitution shape that turned `add_workorder NoSuchJobType 5` into five beds
— so an agent asking for a Still got a carpenter and the brewing it was planning quietly
never happened.

**Measured:** `Still` 1 → 2; `NoSuchWorkshop` leaves the Carpenters count unchanged.

**It tries more than one spot now.** Placement walks a ring around the wagon, and one
attempt was enough on an empty embark and silently did nothing once the ring filled:
measured on a fort with eight workshops, `build_workshop Still` reported success zero
times while sixteen logs sat free. It tries twelve positions before giving up, which is
what a player does — look somewhere else.

**The trap underneath.** `constructBuilding` with no `items` produces a building whose
ConstructBuilding job has no reagent; DF cancels the job and drops the building, and the
caller sees a perfectly successful return value. Measured live: build_workshop reported
success and `world.buildings.all` held nothing but the wagon 20,000 ticks later, while
the identical call WITH a log attached built the workshop. So it claims a reagent up
front and only counts a build when a job with items is actually attached.

Two further traps in choosing that reagent: a workshop is **made of** its log, and handing
that same log to a job destroys the workshop (shops went 1 → 0 the moment a bed job
claimed a reagent); but excluding everything held by a building is far too broad, because
at embark every supply sits inside the **wagon**, which is also a building. So it asks
who holds the item and accepts wagon-held goods.

---

## assign_noble

Put a dwarf in an administrative position.

**Refuses:** a position code the fortress entity does not have.

**Measured:** MANAGER seated, `histfig2 == histfig`, `never_cull` set.

### Two halves of a two-sided link, and DF reads the other one

Writing `entity_position_assignment.histfig` is the obvious move and it is a silent
no-op. The screen field went -1 → 1741 and `getNoblePositions` still returned nothing,
because DF and DFHack both answer "who holds this office?" by walking the **histfig's**
`entity_links` for a `histfig_entity_link_positionst`. MANAGER, BOOKKEEPER and the rest
are SITE positions on the fortress entity; `make-monarch.lua` uses the CIV entity because
MONARCH is a civ position, and copying it verbatim seats nobody.

Even with the link, DF would not accept the officeholder. The difference, found by
running our fort and a hand-played 119-dwarf fort side by side and transplanting our
seating code onto the working one:

| what our code wrote | result |
|---|---|
| `histfig` + the POSITION link | `plotinfo.nobles.manager_cooldown` stayed 0 — DF finds nobody |
| ...plus `histfig2 = histfig` and `hf.flags.never_cull` | cooldown reloaded to 1008 |

Every position DF had appointed itself carried `histfig2 == histfig`; the ones our code
appointed carried `-1`.

**The picker had a second defect.** `pick_best` ranks by skill and had chosen a dwarf who
was **in a military squad**, which DF refuses for an office. Seating a squad-free citizen
on the same fort woke the cooldown within 70 ticks. Reassigning a seat also strips the
POSITION link the previous holder still carries, or two figures claim one seat and DF's
lookup — which walks links, not the assignment — can pick the stale one.

**What is NOT required, measured rather than assumed:** an office. The hand-played fort's
working manager owns a bedroom and nothing else, and removing the previous manager's
office ownership did not stop the cooldown either. Population is not required either:
that was "refuted" once on a miscount (the line printed `#world.units.active`, which was
mostly troglodytes and storks; real `getCitizens` said 7) and then properly refuted at
36 real citizens.

**Still unknown:** why the manager duty never fires on our forts even when seated
correctly. `manager_cooldown` decrements at the normal 1 per 10 ticks and then fails its
check at 0. Population, office, world age, squad membership, order shape, fort rank,
`save_progress`, site links and the embark procedure are all eliminated — including on a
fort DF built itself, through the embark screen's "Start tutorial" button, in a 250-year
world. See `workorder_contract.md`.

---

## add_workorder

Make a specific quantity of something, once.

**Refuses:** any job outside `ORDERABLE_JOBS`. The list is closed at the gate as well as
in Lua, because an open list fails silently: `add_workorder NoSuchJobType 5` used to fall
through to a default and queue five ConstructBed jobs. `MakeBarrel` is in the list and
`ConstructBarrel` is not, because the latter was invented from memory and `df.job_type`
has never had it.

**Deliberately without a condition or a schedule** — that is `add_workorder_conditional`,
a different thing to want even though DF stores both in one `manager_order`. See
`open_decisions.md`.

### Material follows the job, and the wrong one is not a soft failure

`material_category` used to be hardcoded to wood for every job, and the reagent picker
took wood-or-stone whichever it found first — so a bed order could be handed a boulder
once the logs ran out. DF cancels that job thousands of ticks later, with the order's
count already spent on it. Each job now names its (material, workshop, reagent) variants,
and `shop_for` returns nil rather than a fallback: it used to read
`return want and nil or fallback`, which evaluates to `fallback` in **every** branch, so a
brew order would have gone to the carpenter exactly as its comment promised it would not.

### Who owns the count

DF does, and it retires an order sooner than you would expect. Sampling an order every
200 frames while its jobs completed:

    order 6, five jobs queued     left = 6
    ...as each job finished       6 → 5 → 4 → 3 → 2 → 1
    last queued job done          order GONE, with left = 1

So `amount_left` is spent on completion — decrementing at issue time as well double-counted
every job — and **an order is retired as soon as the jobs queued against it are gone,
whatever the count says.** On a normal fort DF's own dispatcher tops the queue back up
first; on ours it never runs, so everything past one workshop-load was silently dropped:
a request for twelve beds delivered five and closed itself claiming to be done.

Ownership is therefore inverted. `_G.BONSAI_ORDERS` is the ledger of what was asked for
and not received; each `df.manager_order` mirrors **one batch** — exactly the jobs queued
for it — so DF's count and its retirement are both correct. Measured end to end: 12
requested, beds 25 → 30 → 35 → 37 over three dispatches, owed 12 → 7 → 2 → 0, then flat.

**The ledger is now on disk too**, beside the actions file as `<actions>.orders`, one
tab-separated line per order. A Lua global dies with the DF process, so a mid-episode
restart — a crash, a watchdog, a reload to inspect something — used to take the
outstanding remainder with it silently: the agent had asked for twelve beds, five were
queued, and the other seven simply stopped existing. Verified by wiping the in-memory
ledger and dispatching again: 12 requested, 3 queued, 9 written, 9 recovered.

**Still unknown:** the ledger is keyed to the actions file path, so two episodes sharing
one path would share one ledger. They are per-episode today, but nothing enforces it.

---

## add_workorder_conditional

Watch a stock level and refill it automatically.

**Refuses:** a job outside `ORDERABLE_JOBS`, an item type DF does not know, and a
comparison or frequency it does not recognise falls back to `LessThan` / `Daily`.

### The shape came off a hand-played fort, not off intuition

    #398 MakeAsh  x5/10  Daily  val=true act=true
         WHILE LessThan 10 of BAR (ASH)

Thirty of that fort's fifty-seven orders carry a condition and every one of those is
Daily. Three things that shape corrected:

* **The amount is the FULL order** (ten ash), not the shortfall. The condition is what
  stops it — once ash reaches ten, `LessThan 10` is false. The first implementation
  ordered `min(batch, below - have)`, which is not a thing DF does.
* **`status.active` means "the condition holds right now"**, not "we approved it". That
  fort carries `#299 SmeltOre val=true act=false` — validated and idle for want of gold
  ore. Forcing `active` erases exactly the bit that expresses the condition.
* **A condition names a material** — `BAR (ASH)`, not any bar — so the stock count filters
  by material and the condition is written into the order's real `item_conditions`. It
  reads in-game and exports through `orders export` like a player's.

**Measured:** fires when stock is below the threshold and stays silent when above; orders
the full amount; the daily schedule holds it back on an immediate re-dispatch and lets it
through once a game day has passed (2 jobs on day 0, 2 more after 1,500 ticks). Restating
an order re-checks it at once rather than waiting out the old schedule.

**Frequency is real game time:** Daily 1200 ticks, Monthly 33600, Seasonally 100800,
Yearly 403200, off an absolute tick so it survives the year boundary.

**Still unknown:** DF's other condition dimensions are not reachable through these
arguments — item flags (`cookable`, `unrotten` on a real `PrepareMeal` order) and
dependencies on another order finishing (`order_conditions`).

---

## build_farm_plot

Lay out a farm plot on ground that suits the crop you mean to grow.

**Refuses:** a plant that does not exist; and any site where the intended crop would not
grow. If nothing suitable is dug out, the count stays at zero and that refusal is the
useful output — it points at `designate_dig`.

**Which ground is right depends on WHAT is being planted.** A subterranean crop in a
surface plot grows nothing while the plot reads as built and sown, and the first version
did exactly that: it built outdoors and sowed plump helmet. That embark happened to ship
six crops that were all `BIOME_SUBTERRANEAN_WATER` — plump helmet, cave wheat, pig tail,
sweet pod, dimple cup, quarry bush — but an embark carrying wheat or another surface
plant wants the opposite ground, so the rule is the crop's, not the species'. The crop is
chosen first and the site demanded to match, falling through the fort's other seeds
rather than building somewhere nothing will grow.

The search runs **down** from the citizen's level as well as across it: dug-out soil is
under the embark, and an earlier pass scanned only the dwarf's own z and found nothing
while 165 usable tiles sat a few levels below.

A plot takes no items to build, so it is finished outright rather than left waiting on a
construction job that carries no reagent, and it is sown on the spot with the crop its
ground was chosen for.

**Measured:** `NO_SUCH_PLANT` refused; `MUSHROOM_CUP_DIMPLE` built at z=49
`outside=false` and sown with dimple cup; `3 3` refused for want of a chamber that size.

**Still unknown:** irrigation. Muddied rock farms too, and nothing here can muddy it, so
the fort is limited to natural soil.

---

## set_crop

Choose what the farm plots grow, per season.

**Refuses:** a plant that does not exist. `best` picks **per plot**, matched to where that
plot is, preferring a crop that can be brewed because drink is what a fort runs out of
first.

**Measured:** every plot on the test fort ends up sown with a crop whose biome matches its
location — the battery asserts this, because sowing the wrong one is invisible.

**Still unknown:** it sets every plot. There is no way to address one plot, and no
per-season planning beyond "all" or one season index.

---

## set_kitchen_flag

Forbid or allow cooking an item type, for every material the fort holds.

**Refuses:** an item type DF does not know.

**Reports reaching the requested state, not only changing it.** DF ships with seeds
already excluded from cooking, so a correct `set_kitchen_flag SEEDS false` looked like a
failed verb until this was fixed.

**Why it matters out of proportion to its size:** cooking destroys seeds, and cooking
drink turns the beer supply into meals. It is pure downside protection and the guide's
most emphasised early setting.

**Still unknown:** it only touches the cookery exclusion (`exc_type` 0). Brewing and seed
use have their own exclusion types and are not reachable, and it works per item type
across all materials rather than per material.

---

## Not yet a tool: brewing

Deliberately absent from `ORDERABLE_JOBS`. Four things are now known for certain, and the
last one is why it is still not shipped.

**1. There is no `BrewDrink` job type.** Not on this build — nothing in `df.job_type`
matches `brew` at all. That is the third enum name written from memory that turned out not
to exist, after `ConstructBarrel` (it is `MakeBarrel`) and a workshop kind that silently
became Carpenters, which is why `bonsai-toolcheck` now asserts every name in `JOB_SPEC`
resolves.

**2. Brewing is a REACTION.** The raws carry `BREW_DRINK_FROM_PLANT` (index 135) and
`BREW_DRINK_FROM_PLANT_GROWTH` (136) among 1,109 reactions. That is also why several of
the hand-played fort's food orders read `CustomReaction` rather than a named job. Plump
helmet's structural material lists `DRINK_MAT` and `SEED_MAT` as its reaction products,
so the staple crop does brew.

**3. DF does not fill `job_items` in for us.** A job created bare at a Still is cancelled
— measured twice. The requirements have to be written by us. This is worth stating plainly
because furniture jobs work *either* way: a pinned item and a specification both produce a
bed, which made it look as though DF was doing the work.

**4. What has been tried and still gets cancelled.** Three shapes, each with 98–102 free
plants and 15 barrels standing in the fort:

| attempt | result |
|---|---|
| `ProcessPlantsBarrel` at a Still, bare | cancelled |
| `ProcessPlantsBarrel` at a Still, with a derived spec — one `unrotten`+`processable_to_barrel` PLANT and one `empty` BARREL | cancelled |
| `CustomReaction` with `reaction_name = BREW_DRINK_FROM_PLANT`, job_items copied verbatim from the reaction's own reagents (2 of 2) | cancelled |

So a `CustomReaction` job needs more than a name and the right reagents. The leads not yet
followed, in the order worth trying:

* the job may need its own index into the reaction list, not only `reaction_name`;
* the Still may need the reaction permitted in its `profile`, the way a workshop's
  `max_general_orders` gates manager orders;
* the fort entity knows 36 reactions (`entity.resources.reaction_idx`) — whether index 135
  is among them has not been checked, and a reaction the civilisation does not know would
  be refused;
* the shipped `workorder` script creates `CustomReaction` orders on the hand-played fort
  that DO run, so its code path is a working example to read rather than reinvent.

**Why it stays out of the tool list meanwhile.** A wrong reagent is not a soft failure:
DF cancels the job thousands of ticks later with the order's count already spent, which is
exactly the silent-success shape every other verb here has been fixed to avoid. Shipping a
brew verb that produces cancelled jobs would be worse than not having one.

`bonsai-brewprobe` builds the current best attempt and reports what DF made of it.
