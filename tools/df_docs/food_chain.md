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

## What actually limits digging

Not what it first looked like. Every pick on this fort carries `item.flags.foreign` —
another civilisation's property, which dwarves will not claim — and that looked like a
complete explanation for dig jobs nobody takes. **Refuted by clearing it:** 14 dig jobs,
23 miners, still zero workers. `foreign` is not even abnormal; the hand-played fort is 13%
foreign items, which is what a few years of caravans looks like.

The real limits are duller:

* **Order.** Tiles one level down are unreachable until the staircase above them is cut,
  and DF says so. A fresh batch of designations looks inert for a while and is not.
* **Picks.** The fort has three, two lying on the ground, so at most three dwarves mine
  however many carry the labour — measured about five tiles per 12,000 ticks.
* **Bad squares.** Played by hand, DF cancelled work with `Dangerous terrain` and
  `Inappropriate dig square`. Neither is visible from designation counts, and neither is
  filtered at designation time yet.

## Brewing: the job was right, the reagent was not

Settled by playing rather than by probing. Drink went **0 → 1** while the farms regrew
plants, with nobody touching the brewing code.

Brewing is a reaction, `BREW_DRINK_FROM_PLANT`; there is no `BrewDrink` job type on this
build. DF does not fill `job_items` in for a DFHack-created job — a bare one is cancelled —
so the requirements must be written, and copying the reaction's own reagents produces a job
DF accepts and a dwarf picks up:

    need type=PLANT sub=-1 mat=-1:-1 qty=1 flags=[unrotten]
    need type=NONE  sub=-1 mat=-1:-1 qty=1 flags=[empty,food_storage]

Every earlier attempt failed on plants synthesised with `createItem`, which DF refuses as
"unrotten plant" — its own words, read out of `world.status.announcements`. A plump helmet
the farm actually grew is accepted. It also needs an **empty container the fort owns**: 14
of this fort's 15 barrels belong to another civilisation.

So the remaining work to make brewing a verb is bookkeeping, not discovery: order the
reaction the way `add_workorder` orders a job, and guard it on a real plant and a free
barrel.

## Played by hand, year 3 — what a session actually shows

Seventeen citizens, no food, no drink, 44 beds lying in a pile, two dwarves with a room.
Driven through the guide's order with the live verbs and observed between steps:

    BEFORE          roomed=2  zones=4  furniture=3  food=0 drink=0 plants=53
    bedrooms        create_zone=3 place_furniture=4 assign_room=3
    AFTER           roomed=5  zones=7  furniture=7  food=0 drink=0 plants=53
    dining hall     create_zone=1   place_furniture table/chair -> NOTHING
    farming         set_crop=1 set_labor=2
    AFTER           plants 53 -> 0
    12,000 ticks    plants 0 -> 11,  drink 0 -> 1

Four things learned that no unit test would have shown.

**1. Brewing works. The reagent was the problem all along.** Drink went 0 → 1 while the
farms regrew plants, with nobody touching the brewing code. Every earlier attempt failed on
plants made with `createItem`, which DF refuses as "unrotten plant"; a plump helmet the
farm actually grew is accepted. So the `CustomReaction` job shape recorded above is right,
and the missing piece was never the job.

**2. `place_furniture` refuses correctly and that is the guide's point.** Four beds went
down; tables and chairs produced nothing, because the fort has 44 bed items and no table or
chair items. The order is make the furniture, *then* place it — `add_workorder
ConstructTable` before `place_furniture table`. The verb declining is the fort telling you
what it is short of.

**3. The fort eats faster than it grows.** Plants 53 → 0 in 9,000 ticks with seventeen
dwarves, then back to 11. Raw plants are food, so a farm feeds the fort only if it
outpaces them, and every plant eaten raw is one not brewed. That is what
`set_kitchen_flag` and a brewing order are for, and it is why the measured year ended
drink 12 → 0.

**4. DF names two defects in `designate_dig` out loud:**

    cancels Dig: Dangerous terrain.
    cancels Carve up/down staircase: Inappropriate dig square.

Neither was visible from designation counts. "Inappropriate dig square" is a staircase
marked where one cannot go; "dangerous terrain" is water or a fall. Both are filterable at
designation time and are not filtered today.


## Second session, with the whole guide set

Same fort, now with all 22 verbs. The point was to run the guide's order properly rather
than one link at a time.

    START          cits=17 roomed=9  food=0 drink=1 plants=11 wood=21
    dig + priority designate_dig=60  set_dig_priority=215  set_labor=1
    wood + policy  chop_trees=9      set_standing_order=1
    AFTER          wood 21 -> 20
    make furniture add_workorder=4   (ConstructTable x3, ConstructThrone x3)
    AFTER          wood 20 -> 18,  plants 11 -> 13
    furnish        place_furniture=1
    standing order add_workorder_conditional=1  (keep 8 barrels)
    AFTER          wood 18 -> 15

**The lesson from session one held.** `place_furniture` produced nothing for tables last
time because the fort had no table items. Ordering `ConstructTable` first and *then*
placing worked — and the wood count falling 21 → 20 → 18 → 15 is the fort actually
spending logs on furniture rather than the verbs merely reporting numbers.

**A new cancellation reason appeared, and it is one we can act on:**

    4  Item inaccessible.
    3  Needs unrotten processable (to barrel) plant.
    2  No food available.

`Item inaccessible` is exactly what `bonsai-reach` measures — stock the fort owns and
cannot walk to. It had been invisible; four jobs died of it in one session.

**What the fort still cannot do is feed itself.** Food has been 0 throughout, plants hover
around 11 because seventeen dwarves eat them as fast as the farm grows them, and drink sits
at 1. Every verb works; the *policy* of using them does not exist yet. That is the
controller's job, and it is now a question about play rather than about tools:

* the farms are small and there are two of them
* nothing cooks, so nothing is preserved
* raw plants are eaten before they can be brewed, which is what `set_kitchen_flag` and a
  standing brew order are for
