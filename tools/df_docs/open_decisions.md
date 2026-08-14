# Open and questionable decisions

Decisions taken under uncertainty, and ones the owner has overruled. Recorded here rather
than left in a commit message, because the reasoning matters more than the diff.

---

## Collapsing bulk creation and stock automation into one verb — REJECTED by the owner

**Date:** 2026-08-15
**Status:** reverted, two verbs kept separate

I proposed a single `add_workorder` carrying optional condition and frequency arguments,
on the grounds that DF stores both shapes in one `manager_order` struct — the automatic
ones simply have `item_conditions` and a `frequency` filled in, the one-off ones leave
them empty. Structurally that is true, and the shipped orders libraries
(`hack/data/orders/*.json`, 45 orders in `basic` alone) are exactly that struct with
conditions attached.

The owner rejected it, and the reason is about intent rather than storage:

> ворк ордер это запрос на создание конкретное количество чего то … а именно orders для
> того чтобы автоматически отслеживалось количество каких то ресурсов и что то
> автоматически попалнялось без ручных отдельных запросов, две задумки, одно
> автоматизация, другое массовое создание

Two different things the agent wants to express:

| intent | verb | shape |
|---|---|---|
| bulk creation — "make twenty beds" | `add_workorder` | job, amount, material |
| automation — "never fewer than five barrels" | `add_workorder_conditional` | job, amount, item, comparison, value, material, frequency |

Merging them made the simple case carry the machinery of the complicated one: a plain
request for twenty beds had to step over five condition arguments it did not want, and
the verb's own schema stopped saying which of the two things it was for. The action
catalog is a statement of what a player can *mean*, not a mirror of how DF happens to
store it.

The implementation underneath is still shared — one ledger, one dispatcher, one job
shape — so the two verbs cannot drift apart on workshop, reagent or accounting.

**What is still open:** whether the automation verb should also express DF's other
condition dimensions, which a hand-played fort does use — item flags (`cookable`,
`unrotten` on a real `PrepareMeal` order) and dependencies on another order finishing
(`order_conditions`). Neither is reachable through the current arguments.
