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
