# Where the atomic-action work stopped

Paused 2026-08-06, mid-way through giving the agent player parity. Nothing is half-applied
to the live system: the action library is committed and passing, and everything below is
either done or not started. Read this before picking it up again.

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
