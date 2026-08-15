# Buildings: room templates and workshop clusters

The owner's design, recovered from the original voice message (2026-08-05) after the
catalog notes turned out to hold only a summary. Quoted where the wording matters, because
three details had already been lost once.

## What was asked for

**Room templates, built on the game's own template system:**

> использование именно **шаблонов внутри игры внутри двхака**

Not a homegrown format. DFHack ships quickfort and a blueprint library — `bedrooms/`
(28, 48 and 95-room layouts), `tombs/`, `dreamfort.csv` (a complete self-sustaining fort),
`aquifer_tap.csv`, `pump_stack.csv`, `exploratory-mining/`, `layout-helpers/`. Format is
CSV with a header like `#dig label(dig) start(12; 12) 28 bedrooms, 3 tiles each`.

**Quality tiers, sourced rather than invented:**

> чтобы мы сделали офис такого-то уровня… **эти уровни и требования полностью есть в Вики**

**A system, not a one-off:**

> сделать… небольшую систему, где каждый дизайн… потом мы сделаем так, чтобы **дизайны
> генерировались с определёнными требованиями**… потом мы смогли **отследить, какой самый
> лучший** из этих дизайнов, тем самым **эволюционными методами** получается лучший…
> возможно прикрутить **метод отжига**… для офисов, комнат, кухонь

and, decisively for where this code lives:

> **отбор комнат уже вести вне обучения основного Агента**
> возьмём что-то за основу и дальше этими методами это будет улучшаться

So: seeded from the shipped blueprints, generated against a requirement, tracked, and
improved by search — all of it OUTSIDE the agent's training loop. The agent picks a name
and a tier and never learns floor plans.

**Workshop clusters, chosen on declared numbers:**

> библиотека кластеров… они **могут быть разных размеров**… среди чего должен агент
> выбирать — это их **цена создания**, можно просто в каких-то числах, и **количество их
> возможностей**, и **что можно восполнить, если их построить**… **когда мы можем посылать
> рабочих** — это тоже можем сделать

Four properties, three of which the catalog had lost: several **sizes** per cluster, build
**cost**, **capability count**, what it lets the fort **replenish**, and the ability to
**send workers** to it.

Framing, repeated twice in the same message: **everything a human player can do, the agent
must be able to do**, and **build the library first** — "это наша первостепенная большая
задача".

## The plan, as atomic goals

Each goal names the self-check that proves it, because a verb that reports success while
doing nothing is this project's defining failure mode.

| # | goal | self-check |
|---|---|---|
| 1 | **Read room value from DF** — the objective function the search optimises | read a furnished office and a bare bedroom on the live fort; the ordering must match what is in them |
| 2 | **Record the quality tiers** from the wiki, per room type | a table in the repo, and a test that tiers are ordered, cover 1..5, and every live zone kind maps to one |
| 3 | **Apply a template through quickfort** — DONE | `apply_template` stamped `library/pump_stack.csv` at 95,83,48 through the real dispatcher; designations verified on the map, not from quickfort's own statistics line |
| 4 | **Index the template library** — shipped plus ours, with footprint, product and target tier | a test that every entry parses, declares a footprint, and names a room kind the catalog knows |
| 5 | **Build the cluster library** — sizes, cost, capabilities, what it replenishes | a test that each declared cost equals the sum of its workshops' real material needs; a live check that applying one builds every workshop reachable |
| 6 | **Ship `build_workshop_cluster`** — the cluster, the stockpiles that feed it, and workers sent to it | a `bonsai-toolcheck` case: every workshop exists and is reachable, and an unknown cluster name is refused |
| 7 | **Offline design search** — generate to a requirement, score by measured room value, improve by annealing or evolution | deterministic under a fixed seed; the best design must beat the seed it started from |

Goals 1 and 2 gate 7 — there is no search without a score and a target. Goal 3 gates 4 and
therefore `apply_template`. Goals 5 and 6 are independent of the rest and can land first.

## Order of work

1, 2, 3 in parallel (discovery), then 4 and 5 (libraries — the owner's stated priority),
then 6 (the verb), then 7 (the search, which needs 1, 2 and 4 in place).

## What is deliberately NOT in scope

The agent learning layouts. The whole point of the tier argument is that it does not have
to: the search runs offline against room value, and the agent asks for "bedroom, tier 3".

---

## Discovery, done and verified

Four investigations, each adversarially re-checked by a second pass. What they settled:

### Room value — goal 1, DONE

**`getRoomValue` does not exist in v50.** Grepping all 153 df-structures files returns
nothing, and DFHack's own `Buildings::getRoomDescription` has its entire body commented
out with `TODO: understand how this changes for v50`. A civzone carries no value at all:
`getPersonalValue(owner)`, `getPersonalValue(nil)` and `getArchValue()` are 0 on every one.

DF only produces the number in its UI layer, per **unit**, in
`view_sheets.curroom[df.demand_room.<kind>]`, recomputed each render frame while a unit
sheet is open — so it needs an owner and a live sheet, and is useless as a scorer.

It is exactly reproducible offline:

    value = (extent cells that are set) + Σ getPersonalValue(nil) over contained_buildings

Validated against DF's own `curroom` on three independent rooms — a 5×5 office with a
throne and two beds (59), a 3×3 bedroom with one superior bed (32), a bare 2×2 bedroom (4)
— exact on all three. `contained_buildings` is maintained by DF, so no spatial matching is
needed. Furniture value equals `dfhack.items.getValue` of the item it is made of, measured
on four pieces (ordinary 10, well-crafted 14, superior 23).

**Bound on this number:** the per-tile term is confirmed only for ROUGH floor, and the
evidence base is narrower than "three rooms" sounds. All three were **outdoor patches at
z=49**, some tiles carrying saplings or shrubs, on a fort with zero engravings — not one
dug-out fortress room was measured. DF's UI says smoothing, engraving, grates, windows,
statues and displayed items raise value; none of that is in the formula, so a finished
room will score low here until the per-tile term is re-measured underground.

Shipped as `bonsai-roomvalue`. Verified live on a fresh 3×3 bedroom: `value=9 (9 tiles +
0 furniture)`.

### Quality tiers — goal 2, CORRECTED

The first version of this section, and the table shipped with it, were **wrong**. They
carried DFHack's `dfhack_room_quality_level` constants —
`0 · 100 · 250 · 500 · 1000 · 1500 · 2500 · 10000`, claimed identical across all four room
types — as though they were v50's. They are pre-v50, and the game refuses them.

**The names, read out of the binary.** 29 contiguous strings, four blocks, descending,
each ending in a rung DFHack has never had:

| room | rungs | ladder, best first |
|---|---|---|
| Office | **7** | Royal Throne Room · Opulent Throne Room · Splendid Study · Decent Study · Modest Study · Meager Study · No Study |
| Bedroom | **8** | Royal Bedroom · Grand Bedroom · Great Bedroom · Fine Quarters · Decent Quarters · Modest Quarters · Meager Quarters · No Quarters |
| Dining | **8** | Royal · Grand · Great · Fine · Decent · Modest · Meager · No Dining Room |
| Tomb | **6** | Royal Mausoleum · Grand Mausoleum · Fine Tomb · Servant's Burial Chamber · Grave · No Tomb |

The differing lengths are on their own enough to refuse an eight-entry uniform table. v50
also renames the office ladder to **Study**: `Splendid Office`, `Throne Room`,
`Burial Chamber`, `Mausoleum` and a bare `Tomb` all return **zero** hits in the binary.

**The cutoffs are NOT established, and the module says so.** `getRoomDescription` is the
only API that would name a tier, and on this build it is the commented-out stub: called
live against a fresh zone, with an owner and without one, it returned `""` both times.
`bonsai-roomvalue` carries `LADDER_CUTOFFS_KNOWN = false` and the battery asserts it stays
false until a measurement backs it.

**What replaces the tier as a target.** DF states, per position, the room value that rank
demands — read live from `entity_position.required_office/bedroom/dining/tomb`, so it is
the game's number and not a remembered one. "A bedroom good enough for a baron" is a
target the search can optimise against; "tier 3" never was.

| demand | positions |
|---|---|
| 1 | captain, manager, bookkeeper (office only) |
| 100 | lieutenant, sheriff |
| 250 | captain of the guard, dungeon master |
| 500 | mayor, baron, general (office) |
| 1500 | outpost liaison, diplomat, count |
| 2500 | duke |
| 10000 | monarch |

The battery re-reads all 15 positions from the world every run and fails if the recorded
table has drifted. Note the wiki was unreachable throughout; nothing here came from it.

### quickfort — goal 3, the mechanism is known

* `quickfort run -c x,y,z <blueprint>`; `--cursor` is **mandatory** headless, because
  `do_command` starts with `guidm.getCursorPos()` which is nil for us. Without it quickfort
  says so and stops.
* `-d/--dry-run` exists and works.
* Position semantics differ between the two entry points, and this is the trap: on the CLI
  the cursor lands on the blueprint's `start()` cell, so `start(12;12)` with `-c 100,100,48`
  puts the top-left corner at 89,89. The `apply_blueprint` API instead simply ADDS pos to
  the data indices and ignores `start()` entirely.
* Valid modes are `dig build place zone burrow meta notes ignore aliases`. **`#query` and
  `#config` are dead** — silently downgraded to `ignore`, so an old blueprint applies its
  other sections and drops those without an error.

### Workshop build cost — goal 5's numbers

`dfhack.buildings.getFiltersByType(argtable, type, subtype, custom)` returns the real
requirement, transcribed in DFHack from DF's own hardcoded table. Measured for all 25
workshop types. Most cost one building material; the exceptions matter:

| workshop | cost |
|---|---|
| most (Carpenters, Masons, Craftsdwarfs, Still, Loom, Tanners …) | 1 building material |
| Siege | 3 building materials |
| MetalsmithsForge | an ANVIL + 1 fire-safe material |
| MagmaForge | an ANVIL + 1 magma-safe material |
| Quern | a QUERN item |

`df.global.buildreq.requirements` is where DF states it, but it is only populated while
the build-placement UI has a building selected — 0 entries headless — so the DFHack table
is the practical source.


## quickfort — goal 3, DONE, and the three traps it hid

`apply_template` is live and was proved through the real dispatcher on a live fort, not by
calling quickfort by hand. Each of the three things below made it silently do nothing
first.

**The anchor.** quickfort's CLI lands the cursor on the blueprint's own `start()` cell, not
its top-left. `library/tombs/Mini_Saracen.csv` declares `start(6;6)`; run at `-c 100,90,45`
it put designations in **95,85 .. 105,95**. The `apply_blueprint` API does the opposite and
ignores `start()` entirely. `library.cursor_for(t, x0, y0)` does the subtraction and is
pinned to that measurement in a test.

**Which blueprint.** A .csv holds SEVERAL blueprints and `quickfort run <file>` runs the
first. `library/pump_stack.csv` opens with a `#notes` help section, so running the file
printed a walkthrough and stamped nothing; Mini_Saracen worked only because its first
section happens to be `#dig`. Everything else must be named `-n /<label>`, so every
template now carries its label.

**Which fit test.** A `#dig` blueprint is *supposed* to go into solid rock, so asking
`reach.site` — every tile a free floor — refused every dig design on a fort made of stone.
That is the wall-is-not-walkable confusion one layer up. `bonsai-reach` gained `dig_site`,
and each template declares `label_mode` so the dispatcher picks the right question.

### And the footprint was measuring the wrong thing — goal 4, CORRECTED

`footprint` was comma-fields wide by lines tall: the shape of the FILE. That number cannot
answer the only question a footprint is for. Mini_Saracen read 12x26 and stamps 11x11;
dreamfort read 42x3238 and stamps 34x35 over two levels. Every entry passed its test and
every entry was wrong. `blueprint_extents` now parses sections, `#` fences and `#>`
z-steps — respecting CSV quoting, without which the three `bedrooms/` files read as having
no dig section at all — and the 11x11 is pinned to the live map.

### Placement was quietly finished, everywhere

Chasing the fit test surfaced a defect in four verbs at once. The shared placement ring
samples eight compass points, widening every eighth step; once those samples are occupied
it keeps proposing taken ground, so `build_workshop`, `create_stockpile` and `create_zone`
had stopped placing anything on the test fort while an independent scan found free sites a
few tiles away. `find_site` now falls back to an outward scan when the ring is used up. The
same battery that exposed it confirmed the fix: 45 pass / 3 fail before, 50 / 0 after.


## Goals 5, 6 and 7 — DONE, and what each one overturned

### The cluster library — goal 5

Both numbers the agent chooses on were wrong. **Cost** was `len(workshops)`; DF's own
build-filter table, read live with `getFiltersByType` across all 23 workshop types and all
7 furnace types, charges Siege and the Ashery three and the forges, the Dyer's and the
Millstone two. Seven buildings also demand items no fort has at embark — a manufactured
QUERN, a MILLSTONE plus TRAPPARTS, an ANVIL, an EMPTY barrel — now `Cluster.needs`, with
`Cluster.prereq` naming what must be built first.

**Capability** now counts DISTINCT member kinds, from DFHack's `getJobs`. Two Carpenter's
workshops unlock no new job; they buy throughput. The figures are WORLD-SPECIFIC and
labelled so: `getJobs` appends one `SmeltOre` per ore-bearing inorganic (16 here) and the
Craftsdwarf's 631 is one job kind repeated per instrument.

Two proposed keys named buildings that do not exist: quickfort's `wS` and `wp` are
`workshop_type.Custom`, not enum members.

### build_workshop_cluster — goal 6

All or nothing, and it undoes a partial placement. Measured live: `survival` raised 2
shops and 3 piles, `milling` was refused on a fort with no quern, an invented member was
refused, and 12 stockpile links were written with **0 one-sided**. A workshop has no
`links` field at all — its four vectors are at `profile.links`.

Sending workers is NOT wired. The field exists (`profile.permitted_workers`, verified
live) and the owner asked for it; saying so beats a verb that appears to do it.

### The offline design search — goal 7

`lab_agent/bonsai_lab_agent/design/`, run outside the agent's loop, as instructed.

**The objective was wrong before it was written.** The per-tile term is not 1 — a smoothed
tile is worth 4, measured against DF's own `curroom`. A search over the old number would
have produced a confident artefact.

It **minimises cost subject to meeting a DEMAND** rather than maximising value. Maximising
value returns "dig out the level and fill it with statues", and worse, it pretends to rank
designs above the target when `LADDER_CUTOFFS_KNOWN` is false and nothing can tell a good
room from a better one once both satisfy the noble.

The exploit it would otherwise find is real and is refused in the representation: DF
prices a WALL inside the extent the same as a rough floor, so a zone painted over bedrock
is free value.

Annealing rather than a GA, with the owner's evolutionary idea as elitist restart:
crossing two valid rooms of different sizes produces an invalid room almost surely, so a
GA would spend its budget in a repair operator.

**The game found a bug in it.** The first emitter put `s` on a cell to be smoothed, which
replaced its `d`; quickfort's dry run answered *"Tiles that could not be designated for
digging: 11"* against exactly the 11 smooth cells — you cannot smooth rock nobody has
mined. Smoothing is now its own pass, and the same design designates all 43 and fails
none. That is the offline model and the game agreeing, which is the only check worth
having.

Measured: mayor's bedroom, score -39168 -> -141, value 500 against a demand of 500.
