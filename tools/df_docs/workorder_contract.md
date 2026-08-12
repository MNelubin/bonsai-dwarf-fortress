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

## The office: built, but probably not a valid room yet

Guides are unanimous that an office is step 2 of setting up work orders and the number one
reason they never fire — "a manager only performs their duties in their office". The
beginner video's line about twenty dwarves is about VALIDATION, not about whether the
manager functions, and reading it the other way cost a day.

Built the chain and it mostly works now:

| step | result |
|---|---|
| `ConstructThrone` as a direct workshop job | chair item made |
| place the chair as furniture | `chairs=1` — first furniture our code has ever placed |
| create the Office civzone | `zones=1 offices=1`, id 3 |
| assign it to the manager | `assigned_unit_id = 1548`, ok |
| the order | still `val=0 act=0 left=2` |

Two things learned, both reusable:

* **A civzone needs `abstract = true`.** `dfhack.buildings.constructBuilding` without it
  just fails, which is what the earlier "office zone ok=false" was. Quickfort's
  `internal/quickfort/zone.lua:365` is the reference implementation.
* **Telling a building's material from its contents:** `contained_items[].use == 0` means
  the item IS the building; anything else it holds is ordinary stock. A filter that
  rejected everything a building holds threw away our own workshop's output and could not
  find the chair it had just made.

**Not finished:** `bld.room.extents = <uint8_t array>` fails, so the zone has width and
height but no per-tile extents. Quickfort passes extents through `fields` at construction
time via its own `make_extents`; assigning afterwards does not take. Until that works the
office is probably not a room DF recognises, so **this run does NOT show that an office
fails to fix work orders** — it shows that we cannot build a valid office yet.

Next: use quickfort's `make_extents` (or replicate it) and pass `fields.room` at
construction, the way `create_zone` does.

Meanwhile the direct workshop-job path works and produces beds, so the agent is not
blocked on this.
