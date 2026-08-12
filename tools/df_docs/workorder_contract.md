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

Meanwhile the direct workshop-job path works and produces beds, so the agent is not
blocked on this.
