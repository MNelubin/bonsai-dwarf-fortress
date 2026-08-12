# Where the atomic-action work stopped

Paused 2026-08-06, mid-way through giving the agent player parity. Nothing is half-applied
to the live system: the action library is committed and passing, and everything below is
either done or not started. Read this before picking it up again.

## The manager hypothesis — TESTED, AND IT DID NOT HOLD

The theory was that `workorders_done` sat at 0 for a game year because `MANAGER` is
vacant on the pinned save and the publisher's guide says the manager is what turns an
order into a job. Tested live on 2026-08-06.

Confirmed by probe: `MANAGER` exists as position id 10 with `required_office = 1`, and
its assignment slot held `histfig = -1`. Seating a citizen worked at the field level —
`histfig` went -1 → 1741, assignment slot id 6.

Then nothing happened. Over 6,000 ticks the order stayed `validated=0 active=0
amount_left=5`. **Writing `assignments[i].histfig` is not enough to make the game treat a
dwarf as the manager.** This is the same shape of bug as the dig designations that wrote
cleanly and generated zero jobs: the field looks right and DF never notices.

Most likely missing pieces, in order of suspicion:

1. DF tracks a noble through the histfig's own entity links
   (`histfig_entity_link_positionst`), not only through the entity's assignment vector.
   Seating probably has to create that link too.
2. The manager may need the office its position demands before it will validate anything,
   even though the guide says the office is not required below twenty dwarves.
3. Validation may be a job the manager has to physically perform, so it needs an idle
   manager and possibly a specific trigger.

So the root cause of `workorders_done == 0` is still **open**. It may not be the manager
at all — a bare `manager_order` carrying only a `job_type` may simply not be a valid
order. `manager_order` turns out to have `reaction_name`, `material_category`,
`item_conditions` and `order_conditions` fields, and a real order made through the UI
fills more of them than we do.

Next experiment: place an order through DFHack's own `orders` plugin (which imports
orders players actually use) and diff its fields against one of ours. That isolates
"our order is malformed" from "our manager is not real".

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
