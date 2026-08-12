# Atomic actions — state as of 2026-08-06

Everything below is either done and verified on a live fort, or explicitly not started.
Read this before picking the work up again.

## The chain works end to end

For the first time, an agent intent turns into a manufactured object:

    APPLY build_workshop=1   ->  shops=1, still standing 16,000 ticks later
    APPLY add_workorder=2    ->  BEDS=2, logs 3 -> 1

Verified through the real dispatcher, not a probe script.

## Three stacked defects, all fixed

**1. `build_workshop` was a silent no-op.** `dfhack.buildings.constructBuilding` with no
`items` returns a valid-looking building whose build job has no reagent; DF cancels the
job and drops the building while the caller sees success. Measured: `APPLY
build_workshop=1`, then 20,000 ticks later `buildings.all` held only the wagon. This alone
explains `workorders_done == 0` for a whole game year — there was never a workshop to work
in. It also explains why the `buildings` observable looked like progress: stockpiles are
abstract and need no construction, so the count rose on those alone.

**2. Manager orders do not work here, and it is not our code.** With the manager seated
(`getNoblePositions` confirms), the carpenter at `construction_stage=3`,
`status.validated` and `.active` forced, `material_category.wood` set,
`frequency=OneTime`, six idle CARPENTERs and three free logs — no job in 15,000 ticks.
DFHack's own `workorder '{"job":"ConstructBed","amount_total":3}'` behaves identically.
Seven causes eliminated one at a time; the mechanism remains unexplained and unused.

**3. The guide never used a manager order for this.** At 17:10 it clicks the carpenter and
adds a task *directly to the workshop* — no manager, no validation, no office. At 18:19 it
says outright that the office is not required until twenty dwarves, which kills the office
theory for a seven-dwarf fort. `add_workorder` now creates jobs on the workshop:
`addGeneralRef(BUILDING_HOLDER)` + `shop.jobs:insert` + `linkIntoWorld` +
**`attachJobItem`**. Beds appear within 4,000 ticks.

**The unifying rule, learned three times in one day:** anything DFHack creates without an
explicit reagent is cancelled by DF and silently removed.

**Reagent selection has a trap on both sides.** Handing a job the log a workshop is MADE
of destroys the workshop (`shops` 1 → 0 the instant a bed job claimed one). But guarding
on `flags.in_building` is far too broad — at embark every supply sits inside the WAGON,
which is also a building, and that version left the fort unable to build anything at all.
The working rule asks `dfhack.items.getHolderBuilding` and accepts an item held by nothing
or by the wagon.

## Seating nobles: solved

`assign_noble` is live. DF and DFHack resolve an office holder by walking the appointee's
`historical_figure.entity_links` for a `histfig_entity_link_positionst`, not by reading
`assignment.histfig` — writing that field alone moved it -1 → 1741 while
`getNoblePositions` still returned nothing. Verified: `APPLY assign_noble=2`, unit 1548
holding `MANAGER,BOOKKEEPER`, the pre-existing `EXPEDITION_LEADER` untouched.

Trap: `MANAGER` and friends are **site** positions on `plotinfo.main.fortress_entity`.
`make-monarch.lua` uses the **civ** entity because MONARCH is a civ position, so copying
it verbatim seats nobody.

Note it did NOT fix work orders — that hypothesis was mine and it was wrong.

## The action library

`lab_agent/bonsai_lab_agent/actions/` — a verb is a declaration (name, typed args, the
observable that proves it worked, tranche). The gate repairs scale mistakes, refuses
category mistakes, returns a reason for every refusal, and hands the controller a 1.5 KB
schema. **7 live, 17 planned.** Wired into `game_scorer.sanitize_actions` and into the
recorder, so refusal reasons are audit evidence in replays. 200 tests pass.

## Not started

Tranche 1 is now `build_farm_plot`, `set_crop`, `set_kitchen_flag`,
`add_workorder_conditional` — what remains of the chain from dirt to a mug of beer, which
is where the measured year run died (drink 12 → 0, nothing brewed, 2 of 7 dead).

`add_workorder_conditional` needs rethinking: it was specified against manager orders,
and manager orders do not work here. A standing order may have to be re-implemented as
evaluator-side bookkeeping that re-issues direct workshop jobs when a stock level falls.

Tranches 2–4 (zones, furniture, terrain vocabulary, templates) are untouched. The
room-template library and the offline design search have not been started; DFHack ships
`quickfort`/`blueprint`, which is the natural storage format and would save inventing one.

## Structures pinned by probe

| thing | where |
|---|---|
| noble positions | `plotinfo.main.fortress_entity.positions.own` (`.code`, `.id`), holders in `.assignments` (`.position_id`, `.histfig`, -1 = vacant) |
| kitchen flags | `plotinfo.kitchen` — five parallel vectors of length 110, plus `kitchen_exc_type` = {0 Cook, 1 Brew} |
| farm plot | `df.building_type.FarmPlot` = 4; `building_farmplotst.plant_id` is `int16[4]`, one per season |
| work order | `manager_order` has `reaction_name`, `material_category`, `item_conditions`, `order_conditions`, `frequency`, `max_workshops`, `status.{validated,active}` |
| brewing | no `job_type.BrewDrink` in this build — brewing is a reaction, so `reaction_name` matters |

Absent here, do not reach for them: `dfhack.matinfo.getTile`, `world.kitchen`,
`world.manager_order_next_id`.

## Research notes

`capability_report.md` — what a player can do, checked against the guide and the wiki.
Sound; it had its verification pass.

`tranche1_contracts.md` and `contracts_partial.md` — leads with citations, not settled
facts. Their skeptics confirmed nothing (they were told to default to "does not hold"),
and `contracts_partial.md` is missing four of seven lanes and its synthesis entirely. The
`assign_noble` contract is the one lead so far to survive contact with a live fort.

The guide transcript and raw captions are third-party material and stay out of git (see
`.gitignore` here); regenerate with `yt-dlp` if needed.
