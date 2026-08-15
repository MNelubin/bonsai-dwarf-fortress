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
| 3 | **Apply a template through quickfort** | apply a shipped `bedrooms/` blueprint at a chosen spot on a live fort; designations and zones appear where they should |
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

**Bound on this number:** the per-tile term is confirmed only for ROUGH floor. All three
measured rooms were unsmoothed and the fort had zero engravings. DF's UI says grates,
windows, statues and displayed items raise value; none of that is measured, so a smoothed
or decorated room will score low here.

Shipped as `bonsai-roomvalue`. Verified live on a fresh 3×3 bedroom: `value=9 (9 tiles +
0 furniture) tier=1 Meager Quarters`.

### Quality tiers — goal 2, DONE

Thresholds are **identical across bedroom, dining room, office and tomb**; only the names
differ. Confirmed on five independent wiki pages.

    0 · 100 · 250 · 500 · 1000 · 1500 · 2500 · 10000

The v50 page is **`Zone § Quality and value`** — main-namespace `Room` is tagged obsolete
because as of v50.01 rooms are activity zones. The wiki was unreachable directly and every
figure came from web.archive.org snapshots, which is recorded rather than glossed.

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
