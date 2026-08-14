# Work order contract (DFHack `orders` plugin, DF 53.15)

The formal schema the `orders` plugin reads and writes. This is the thing to validate an
agent-supplied order against, and it is far more expressive than the bare
`job_type` + `amount` our dispatcher has been emitting.

Source: `plugins/orders.cpp` in DFHack (export/import round-trip), cross-checked against
the six libraries shipped at `hack/data/orders/*.json` — `basic`, `furnace`, `glassstock`,
`military`, `rockstock`, `smelting`. `basic.json` alone holds 45 orders.

## Order object

Keys actually present across the shipped library:

| key | meaning |
|---|---|
| `job` | `job_type` enum key, e.g. `ProcessPlantsBarrel`, `PrepareMeal` |
| `reaction` | reaction code, when `job` is `CustomReaction` |
| `item_type`, `item_subtype` | raw tokens, not numbers; item type falls back to the job's implied item |
| `material` | material token via `MaterialInfo::getToken` |
| `material_category` | array of flag names, e.g. `["wood"]` |
| `item_category` | array of flag names (from `specflag.encrust_flags`) |
| `meal_ingredients` | only for meal jobs |
| `amount_left`, `amount_total` | integers |
| `frequency` | enum key: `OneTime`, `Daily`, `Monthly`, `Seasonally`, `Yearly` |
| `id` | remapped on import; ids come from `world.manager_orders.manager_order_next_id` |
| `is_validated`, `is_active` | the two status bits, flattened |
| `workshop_id`, `max_workshops` | target a specific shop, or cap how many take it |
| `item_conditions` | see below — this is where the power is |
| `order_conditions` | `{order: <id>, condition: <enum key>}`, a dependency on another order |
| `hist_figure`, `art`, `name` | artefact/naming detail |

## Item conditions — the standing-order mechanism

Exactly what a player means by "always keep five empty barrels". Each condition:

| key | meaning |
|---|---|
| `condition` | comparison, e.g. `AtLeast` |
| `value` | the threshold |
| `item_type`, `item_subtype` | what to count |
| `material` | material token |
| `flags` | item-flag names, e.g. `unrotten`, `empty`, `processable_to_barrel` |
| `reaction_class`, `reaction_product`, `reaction_id`, `contains` | reagent-level filters |
| `tool`, `min_dimension`, `bearing` | tool use, size, ore-bearing rock |

A real shipped order, `library/basic` id 9, reads: run `ProcessPlantsBarrel`, one at a
time, daily, **while** there are at least 150 unrotten barrel-processable plants **and**
at least 5 empty barrels. Two conditions, and between them they express the whole
standing-order idea without any evaluator-side bookkeeping.

## Notes for our dispatcher

* `is_validated: false` is the NORMAL shipped state — every one of the 45 library orders
  is exported that way. A false `validated` bit is not evidence of a broken order.
* `frequency` in the library is usually `Daily`, not `OneTime`. Ours has been sending
  `OneTime` (and before that `-1`, which the shipped `workorder.lua` treats as fatal).
* `id` must come from `world.manager_orders.manager_order_next_id`, and that counter must
  be advanced. Ours used `#manager_orders.all`.
* Import failures on a single condition are non-fatal: the plugin drops the condition,
  warns, and creates the order anyway — so a partially-valid order silently loses its
  guard. Validate our side rather than relying on the plugin to reject.
* Not serialised at all: the order's `items` list, `finished_year`, condition `flags4/5`.

## Open: getting an order to produce a job headlessly

Still unsolved, and it is a gap in my understanding rather than a proven defect. What has
been eliminated on a live 7-dwarf fort with a finished carpenter:

| ruled out | evidence |
|---|---|
| vacant manager | `getNoblePositions` returns `MANAGER`, `BOOKKEEPER` |
| workshop refuses orders | `profile.max_general_orders = 5` |
| population gate | 7 citizens; wiki says orders proceed without validation below 20 |
| bad order id | took it from `manager_order_next_id`; counter was 0 anyway |
| unvalidated status | forced both status bits |
| no material category | `material_category.wood = true` |
| nobody to work | 6 idle citizens with `CARPENTER` |
| our hand-rolled order | shipped `workorder.lua` behaves identically |
| order shape | tested with a condition and without; `OneTime` and `Daily`; id from the counter and not |
| our advance mechanism | ran the fort FREE for 175,000 frames — no heartbeat, no per-frame popup clearing, no pause rewrites. Order unchanged at `val=0 act=0 left=2`. Also measured ~800 frames/s free-running, well above our chunked advance |

What is left, now that order shape and the advance loop are both eliminated: **the save
itself.** `bonsaifort2` was produced by a scripted headless embark, and something a
normally-embarked fort has may be missing from it.

The experiment that splits this: load one of the other worlds already on the host
(`fort-s650296489`, `fort-calm-s650296489`, `large-257-s650296489` under
`/srv/df-bonsai/worlds/`) and place the same order. Orders working there would pin the
fault to our pinned save. Blocker: DF's save directory on this install is not
`data/save` or `save` — both are empty — and the boot script loads by clicking a name in
the menu, so the path has to be found from DF's own environment first.

A downloaded community save is NOT a route: DFFD hosts v50.x saves and this build is
53.15, which will not load them.

## The office: BUILT, owned, and it did not fix work orders

Guides are unanimous that an office is step 2 of setting up work orders and the number one
reason they never fire — "a manager only performs their duties in their office". The
beginner video's line about twenty dwarves is about VALIDATION, not about whether the
manager functions at all, and reading it the other way cost a day.

So the office got built, properly, and verified at every step:

| step | verified by |
|---|---|
| chair made (`ConstructThrone`, direct workshop job) | chair item exists |
| chair placed as furniture | `chairs=1` — first furniture this code has placed |
| Office civzone, 5x5, with real extents | `zone id=3 Office w=5 h=5 extents set=true` |
| manager owns it | `unit.owned_buildings` -> `owns 3 Civzone` |
| manager is really the manager | `getNoblePositions` -> `MANAGER` |
| the position wants an office | `required_office = 1` |

Order placed after all that, through the shipped `workorder.lua`, `Daily` frequency:
**still `val=0 act=0 left=2` over 20,000 ticks.** No beds.

Three API traps found on the way, all the same shape — one side of a two-sided link:

* **A civzone needs `abstract = true`** or `constructBuilding` just fails. That was the
  earlier "office zone ok=false".
* **Extents must be cast**: `df.reinterpret_cast(df.building_extents_type, df.new('uint8_t', area))`.
  A raw `uint8_t` array assigned after construction silently does not take
  (`quickfort/building.lua:569` is the reference).
* **`assigned_unit_id` does not make a dwarf OWN a room.** With it set, the manager's
  `owned_buildings` was still empty. `dfhack.buildings.setOwner(bld, unit)` is the real
  call — exactly the same lesson as noble seating, where writing `assignment.histfig`
  without the histfig entity link seated nobody.

Also worth recording: **`contained_items[].use == 0`** distinguishes the item a building
IS from stock it merely holds. A filter that rejected everything a building held could not
find the chair the workshop had just produced.

Caveat on the negative: I cannot see the nobles screen to confirm DF paints the office
requirement green. `owned_buildings` containing the zone is the strongest proxy available
headlessly.

## The harness was starving every fort of migrants

Found while chasing the order, and far more consequential than the order itself.

`bonsai-advance2` clears `world.status.popups` and resets `status.flags.DID_ANNOUNCE`
**on every graphic frame**. DF's fort-level services ride on that machinery. With the
heartbeat running, our pinned fort sat at 7 citizens across 48,000 ticks and produced
zero announcements. Advancing the same fort with popups cleared every ~20 seconds
instead of every frame:

    citizens  7 -> 15 -> 18        "Some migrants have arrived."
    announcements 0 -> 59          seasons turning, outpost liaison arriving
    throughput ~5,000 ticks/chunk -> ~15,000, and it no longer stalls

So every episode this project has ever measured ran in a fort that could not receive
migrants. That taints the year-run conclusion ("both policies head for death") — the
forts were being denied their main source of new hands by our own harness, not only by
the policy. The runs need repeating with a coarser heartbeat.

The heartbeat exists for a real reason: a modal popup freezes the sim, and plain
`pause_state = false` advanced the fort by ONE tick in four minutes. So it cannot simply
be removed — the cadence has to be coarse enough to leave the event system alive and
frequent enough to unstick the sim.

## Orders: still not validating on our saves

With the fort alive — migrants, liaison, seasons, 59 announcements — the order placed
through the shipped `workorder` still read `val=false act=false left=2` across a full
game year (year 2 tick 16,801 to year 3 tick 145,907). Population peaked at 18 and fell
back to 15 as unmanaged dwarves starved.

**The population lead is now tested and REFUTED.** Feeding the fort with
`dfhack.items.createItem` (206 plants, 212 drinks) let migration carry it to **21
citizens** — past the 20 the wiki names as the validation threshold. With a manager and
bookkeeper seated, an office built with real extents and owned via `setOwner`, and a
further full game year of running, the order stayed `val=false act=false left=2`
throughout. Being above the threshold changes nothing here.

Also tried and failed this round: forcing a `ManageWorkOrders` job (job_type 195) directly
— it does not stick, the manager never picks it up. And `modtools/create-unit` cannot
raise the population on this build: it drives spawning through the arena screen, and both
`world.arena_spawn` (renamed to `world.arena`) and the keycode `D_LOOK_ARENA_CREATURE` are
gone, so patching the field names is not enough.

Meanwhile the direct workshop-job path works and produces beds, so the agent is not
blocked on this.

## The mechanism, finally measured — and two real bugs in our own code

Everything above was reasoning about a fort in isolation. Running our fort and a
**hand-played 259-year, 119-dwarf fort side by side on the same binary** (ports 5006 and
5005, DF 53.16 + DFHack 53.16-r1.1) turned the guessing into A/B measurement. The
hand-played save is the user's `region3`; it is loaded read-only and backed up at
`/srv/df-bonsai/backups/region3-orig`.

### How validation actually works

Not a timer tick — **a job**. The manager takes `ManageWorkOrders` and performs it. The
clock that schedules it is `plotinfo.nobles.manager_cooldown` (Toady's
`manager_job_delay`, documented range 0–1008):

* it counts down **1 per 10 ticks**, measured identically on both forts
* on reaching 0 DF looks for an officeholder; if it finds one, the duty runs and the
  cooldown reloads to 1008
* with no officeholder it sits at **0 forever** — which is exactly our fort's state

`plotinfo.manager_timer` (`quota_checktime`) is a red herring: it oscillates 0–10 on a
fort with 57 orders and sits at 0 on a fort with one, i.e. it behaves like a cursor into
the order list, and it keeps moving on their fort even with the manager unseated.

### Bug 1 — our orders carried no material, so they could never dispatch

An order created by the shipped `workorder` has `material_category` empty. On the
hand-played fort, `ConstructBed` order #665 sat at `left=2` for 12,000 ticks **while
validated and active**. Setting `material_category.wood = true` on an otherwise identical
order made it complete and vanish from the list. So a validated order is not enough: the
order must name a material class or DF never picks a reagent.

### Bug 2 — `assign_noble` only wrote half the seat, twice over

Proven by transplant: seating a manager with **our own code on their working fort**, and
watching whether `manager_cooldown` reloads within ~2,500 frames.

| what our code did | result |
|---|---|
| wrote `assignment.histfig` + the POSITION entity link | cooldown stayed 0 — DF finds nobody |
| ...plus `assignment.histfig2 = histfig` and `hf.flags.never_cull` | cooldown reloaded to 1008 |

Every position DF had appointed itself on their fort carried `histfig2 == histfig`; the
two our code appointed carried `-1`. On our own fort, `EXPEDITION_LEADER` (seated by DF
at embark) had it; `MANAGER` and `BOOKKEEPER` (seated by us) did not. Same shape as the
two earlier traps in this file — one side of a two-sided link.

The picker had a second defect: `pick_best` ranks by skill and had chosen a dwarf who was
**in a military squad**, which DF refuses for an office. Seating a squad-free citizen on
the same fort woke the cooldown immediately. Both fixes are in `bonsai-apply-actions.lua`,
along with stripping the stale POSITION link a previous holder keeps for a reassigned seat.

### What is NOT required, measured rather than assumed

* **An office.** Their working manager owns a *bedroom and nothing else*, and the
  cooldown cycles normally. Removing the previous manager's office ownership did not stop
  it either. The office presumably still gates the order actually being validated, but it
  is not what our fort is missing.
* **20 population.** Refuted properly this time. The earlier "21 citizens" measurement was
  counting `#world.units.active`, which on our fort is mostly troglodytes and storks —
  `getCitizens` said 7 the whole time. Forcing real migrants with `migrants-now` took our
  fort to **36 citizens** and changed nothing.
* first_year, fortress_rank, `progress_population/production/trade`, `king_arrived`,
  `justice_active`, `save_progress.stage`, site→entity links, `whereabouts.site_id`,
  `assignment_vector_idx`, workshop `profile.max_general_orders`, zone extents byte
  values, `possible_appointable` (MANAGER is correctly absent from ours, so DF does see
  the seat filled).

### Still open

On our scripted-embark save the cooldown **decrements normally** (1008 → 808 over 2,000
frames) and then fails its check at 0, with a manager seated exactly the way that works
on the hand-played fort. So DF reaches the check and rejects our officeholder for a
reason not yet found. Hand-creating the `ManageWorkOrders` job does not help — DF drops
it within a few hundred ticks without assigning a worker, the same as the earlier
`job_type 195` attempt.

The remaining split is: **our embark procedure produces a defective fort**, versus
**something about a 5-year-old world**. The experiment that separates them is a scripted
embark inside the user's 259-year world; `bonsai-setsite.lua` exists for it but the
embark-screen map click still does not select a tile.

### Both were wrong — it is fort size, and DF made the fort itself

The embark screen's **"Start tutorial"** button embarks at a DF-chosen site with one
click, which sidesteps the map-click problem entirely. Using it in one of the shipped
250-year worlds produced a fort **DF created end to end**, in a mature world:

    year 250, 7 citizens, manager_cooldown = 0, order never validates,
    order forced validated+active with 17 free logs and a finished
    Carpenters workshop -> jobs = 0, beds = 0

So it is neither our embark procedure nor the age of the world. A small young fort's
manager machinery is simply dormant, on a save nothing of ours ever touched. The only
fort where any of it works remains the hand-played 119-dwarf one.

## Resolution: the evaluator plays manager

DF will not dispatch, so we do. `add_workorder` now creates a **real `df.manager_order`**
in `world.manager_orders` — visible and countable exactly like a player's — and
`dispatch_orders()` performs the step DF refuses to, emitting the same job shape DF emits
on the working fort, read off it field by field:

| field | value |
|---|---|
| `job.flags.by_manager` | true |
| `job.order_id` | the order's id |
| general ref | `BUILDING_HOLDER` -> the workshop |
| `job_items` | one reagent, attached before the job is left alone |

`shop_for()` maps job type to workshop type so a bed order is never handed to a smelter,
and refuses rather than guessing when the job type is unknown. Capacity comes from the
workshop's own `profile.max_general_orders`, so an order larger than the shop can hold is
issued in batches and **carries forward**: the tail of every dispatch re-visits every
order with `amount_left > 0`, which is the second and every later visit the manager would
have paid. A finished one-time order is retired the way DF retires it.

Measured:

    our fort   ConstructBed x4  -> 4 by_manager jobs, beds 2 -> 6, order retired
    DF's fort  ConstructBed x3  -> beds 0 -> 3, order retired
    DF's fort  ConstructTable x9 -> issued 1 (the shop already held 4 of its 5), order
                                   left 8/9, then drained over three further dispatch
                                   rounds to 11 tables and retired itself

One trap on the way: erasing a finished order from `world.manager_orders.all` **and**
calling `o:delete()` corrupted the vector — it reported zero orders while an unfinished
one was still in it, silently losing the agent's work. The container owns those pointers;
erase only.


