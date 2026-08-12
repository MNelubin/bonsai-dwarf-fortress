# Where the atomic-action work stopped

Paused 2026-08-06, mid-way through giving the agent player parity. Nothing is half-applied
to the live system: the action library is committed and passing, and everything below is
either done or not started. Read this before picking it up again.

## The manager hypothesis — half right, and the important half was wrong

Two separate questions got tangled together. Both are now answered.

**Seating a noble: solved.** `MANAGER` is position id 10 on the fortress entity with
`required_office = 1`, and its slot held `histfig = -1`. Writing that field is a silent
no-op — measured, it moved -1 → 1741 while `dfhack.units.getNoblePositions` still
returned nothing. DF and DFHack resolve an office holder by walking the appointee's
`historical_figure.entity_links` for a `histfig_entity_link_positionst` and binsearching
assignments by the link's `assignment_id`. With the link inserted it works, verified
through the real dispatcher: `APPLY assign_noble=2`, unit 1548 holding
`MANAGER,BOOKKEEPER`, the pre-existing `EXPEDITION_LEADER` untouched. `assign_noble` is
now a live verb.

Trap worth keeping: `MANAGER` and friends are **site** positions on
`plotinfo.main.fortress_entity`. `make-monarch.lua` uses the **civ** entity because
MONARCH is a civ position, so copying it verbatim seats nobody.

**Why work orders do nothing: still open, and it is NOT the manager.** With
`getNoblePositions` confirming MANAGER and BOOKKEEPER, an order stayed
`validated=0 active=0 amount_left=5` across 12,000 ticks. Forcing `validated`, `active`
and `frequency = OneTime` by hand produced no job over another 9,000.

So the fault is in the ORDER. Ours sets only `job_type`; `manager_order` also carries
`reaction_name`, `material_category`, `item_conditions` and `order_conditions`.

**Confound to control for first:** that probe fort had no workshop at all, which alone
could explain the final step. The next experiment is ordered: build the carpenter, place
the order, and only if it still does nothing, diff our order's fields against one created
through DFHack's `orders` plugin.

## Work orders: SOLVED, and the answer was in the guide all along

Three defects were stacked on top of each other. All three are fixed and the whole chain
now runs: build a workshop, order beds, beds appear, workshop survives.

**1. `build_workshop` was a silent no-op.** `dfhack.buildings.constructBuilding` with no
`items` returns a valid-looking building whose build job has no reagent; DF cancels the
job and drops the building while the caller sees success. Measured: `APPLY
build_workshop=1`, then 20,000 ticks later `buildings.all` held only the wagon. That alone
explains `workorders_done == 0` for a game year — there was never a workshop to work in.

**2. Manager orders do not work here at all, and it is not our code.** With the manager
seated (`getNoblePositions` confirms), the carpenter at `construction_stage=3`,
`status.validated` and `.active` forced, `material_category.wood` set, `frequency=OneTime`,
six idle CARPENTERs and three free logs — the order still made no job in 15,000 ticks.
DFHack's own `workorder '{"job":"ConstructBed","amount_total":3}'` behaves identically.

**3. The guide never used a manager order for this.** At 17:10 it clicks the carpenter and
adds a task *directly to the workshop* — no manager, no validation, no office. And at
18:19 it says outright that the office is not required until twenty dwarves, which kills
the office theory for a seven-dwarf fort. `add_workorder` now creates jobs on the workshop
via `job.addGeneralRef(BUILDING_HOLDER)` + `shop.jobs:insert` + `job.linkIntoWorld` +
**`job.attachJobItem`**, and beds get made within 4,000 ticks.

The unifying rule, learned three times today: **anything DFHack creates without an
explicit reagent gets cancelled by DF and silently removed.** It applied to the workshop
building and to the workshop job alike.

**Reagent selection is subtle.** Handing a job the log a workshop is MADE of destroys the
workshop (`shops` went 1 to 0 the instant a bed job claimed one). But excluding
`flags.in_building` is far too broad, because at embark every supply sits inside the
WAGON, which is also a building — that guard left the fort unable to build anything at
all. The working rule asks `dfhack.items.getHolderBuilding` and accepts an item held by
nothing or by the wagon.

Verified end to end through the real dispatcher:

    APPLY build_workshop=1     ->  shops=1, and it stays across 16,000 ticks
    APPLY add_workorder=2      ->  BEDS=2, logs 3 -> 1

## Structures pinned by probe (2026-08-06)

Useful regardless of the above, all read off the live build:

| thing | where |
|---|---|
| noble positions | `plotinfo.main.fortress_entity.positions.own` (`.code`, `.id`), holders in `.assignments` (`.position_id`, `.histfig`, -1 = vacant) |
| kitchen flags | `plotinfo.kitchen` — five parallel vectors of length 110, plus `kitchen_exc_type` = {0 Cook, 1 Brew} |
| farm plot | `df.building_type.FarmPlot` = 4; `building_farmplotst.plant_id` is `int16[4]`, one per season |
| work order | `manager_order` has `reaction_name`, `material_category`, `item_conditions`, `order_conditions`, `frequency`, `max_workshops`, and `status.{validated,active}` |
| brewing | there is no `job_type.BrewDrink` in this build — brewing is a reaction, so `reaction_name` matters |

Absent in this build, so do not reach for them: `dfhack.matinfo.getTile`,
`world.kitchen`, `world.manager_order_next_id`.

## Done and committed


| commit | what |
|---|---|
| `8e62223` | the action library — declarative catalog, typed gate, 6 live / 18 planned verbs |
| `18eefc7` | fog of war recorded in the map track; walls composited over black |
| `71f2431` | palette recolouring — DF draws rock greyscale and tints by material |

`lab_agent/bonsai_lab_agent/actions/` is the piece to build on. A verb is a declaration
(name, typed args, the observable that proves it worked, tranche); the gate repairs scale
mistakes, refuses category mistakes, and hands the controller a 1.5 KB schema so it does
not have to guess argument order. 196 tests pass.

Deploy state: **the library is NOT wired into `game_scorer.sanitize_actions` yet.** The old
six-name gate is still what runs a scored episode. That swap is the first thing to do and
is deliberately small — `sanitize()` returns the same `{"verb", "args"}` shape, so the
DFHack dispatcher does not change.

## The one measurement worth acting on first

On the pinned save only `EXPEDITION_LEADER` is filled; `MANAGER` and `BOOKKEEPER` are
vacant. The publisher's own beginner guide says the manager is what turns a work order
into a job. Our agent has had `add_workorder` all along and `workorders_done` sat at 0 for
an entire game year with workshops standing ready.

The experiment is one episode: assign `MANAGER`, issue the same orders, see whether
`workorders_done` leaves zero. If it does, one cheap verb unblocks a whole scoring term
that has been structurally dead.

## Not started

Tranche 1 (`assign_noble`, `build_farm_plot`, `set_crop`, `set_kitchen_flag`,
`add_workorder_conditional`) is declared but unwired — those are the verbs that turn dirt
into a mug of beer, which is what the measured year run failed at (drink 12 to 0, nothing
brewed, 2 of 7 dead).

## Research: partial, and not safe to build from

`contracts_partial.md` holds 54 proposed DFHack contracts from three of seven research
lanes. **The synthesis never ran and most reviews are missing**, so every `confirmed`
rating in it is the proposing agent's own claim rather than a checked fact. Lanes that
never reported: rooms, blueprints, zones, buildings. Re-run before trusting any of it.

The substrate is promising and worth knowing: DFHack already ships `orders`, `stockpiles`,
`zone`, `buildingplan`, `blueprint`/`quickfort`, `design`, `logistics` and `sort`. Work
orders and stockpile settings appear to serialise already, and quickfort looks like the
natural storage format for the room-template library — which would mean not inventing one.

`capability_report.md` is the analysis of what a player can actually do, checked against
the guide and the wiki. That one had its verification pass and is sound.

## Sources

The guide transcript and raw captions are third-party material and stay out of git (see
`.gitignore` here). Regenerate with `yt-dlp` if needed; the URL is in the ignore file.
