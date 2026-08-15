# The survival chain: dirt to beer

The measured year that killed a fort ran drink 12 → 0 with nothing planted, so this is
the chain that matters. Each link, what works, and what blocks the next one.

    designate_dig → a soil chamber → build_farm_plot → set_crop → plants
                                                                    ↓
                                  set_kitchen_flag (don't cook the seed corn)
                                                                    ↓
                                          BrewDrink at a Still → drink

## Where the soil is

Measured on the test fort, around the shaft head at 104,83,49:

    z=49   surface: GRASS, SOIL, some STONE, open air
    z=48   SOIL  (plus a POOL)
    z=47   SOIL
    z=46   SOIL
    z=45   SOIL
    z=44   MINERAL / STONE  ← soil ends here
    below  rock

So a farm chamber has to be carved in the top four levels. Digging deeper produces rock
floors, which no crop will grow in without being muddied first. `designate_dig` carves
its chambers at `oz-1` downwards, so the first few landings are the farmable ones.

## build_farm_plot needs a CHAMBER, and dig did not make one

`designate_dig` used to carve a staircase plus four one-tile arms at radii 1..3 off each
landing. Connected, diggable, and useless: nothing that needs floor area ever fits.
`build_farm_plot 3 3` refused for want of a 3×3 of dug soil while the fort had plenty of
dug tiles, every one of them a single tile wide.

It now carves a solid `len × wide` room hanging off the shaft (default 4×3), with its
first column adjacent to the stair so every tile stays reachable, and rotates which side
it uses on successive calls so the fort grows instead of re-designating.

## The real blocker underneath: every pick is `foreign`

The chamber change did not produce excavated soil, and the reason is older and larger
than the dig shape. On the test fort, after `set_labor MINE true`:

| | |
|---|---|
| citizens | 41 |
| miners (MINE labour) | 30 |
| picks in the fort | 5 |
| dig jobs posted | 4 |
| dig jobs **with a worker** | **0** |
| idle citizens | 13 |

Thirteen idle dwarves, thirty of them able to mine, four posted jobs, and nobody takes
one. Every pick carries `item.flags.foreign` — an item belonging to another
civilisation, which dwarves will not claim. No pick, no mining, whatever the
designations say.

`foreign` is not by itself abnormal: the hand-played fort carries 13% foreign items,
which is what a few years of caravans looks like. What is wrong is that **our fort's own
picks** are flagged that way — a scripted-embark artefact, and the most plausible
explanation yet for the long-standing symptom that designations produce no excavation.

**Status: strongly indicated, not yet confirmed.** Clearing the flag on three picks and
running was cut short when the reaper reclaimed the instance, so the causal test —
does digging start once the picks are the fort's own — still has to be run. If it holds,
the fix belongs at embark or as an explicit repair verb, not as a silent mutation.

## Brewing is still unshaped

`BrewDrink` is not in the orderable job list because its job shape is unknown, and
guessing it would produce jobs DF cancels thousands of ticks later.

What is known:

* A workshop job whose reagent is a **specification** rather than a pinned item works —
  DF fills it and a dwarf takes it (measured: beds 37 → 38). That is the shape the food
  chain needs, because a real `PrepareMeal` job carries four flag-filtered requirements
  (`unrotten`, `cookable`, one also `solid`) and no item type at all.
* DFHack's shipped `basic.json` has a canonical `PrepareMeal` order — `meal_ingredients:
  4`, conditions `AtLeast 20 {unrotten,cookable,solid}`, `AtLeast 80 {unrotten,cookable}`,
  `AtMost 2000 FOOD {unrotten}` — which is a working example to copy for cooking.
* **None of the six shipped order libraries contains a brewing order**, and no live
  `BrewDrink` job appeared on the hand-played fort during the probe window, so there is
  no canonical example to read. `job_item.flags1` does carry `processable_to_barrel`,
  which is what the barrel-brewing condition in the contract doc refers to.

The next experiment is cheap: build a Still, create a `BrewDrink` job with **no**
job_items, and see whether DF populates them itself. If it does, brewing needs no
guesswork at all.
