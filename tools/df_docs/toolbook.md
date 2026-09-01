# The toolbook

Every verb the agent can dispatch today: what it does, what it refuses and why, what was
measured rather than assumed, and what is still unknown about it.

The organising principle is that **in Dwarf Fortress, through DFHack, almost every failure
is silent.** A write succeeds, a building appears, a job is queued, a count goes up — and
nothing happens, for a reason nobody is told. Every entry below therefore has a
*refuses* section, and most of the measurements exist because a verb once reported
success while doing nothing.

Batteries that keep these honest, both run through the real `bonsai-apply-actions` entry
point on a live fort:

* `bonsai-toolcheck` — one case per verb plus its refusal path (63 pass, 0 fail, 0 skip)
* `bonsai-ordercheck` — the order machinery in depth (23 pass, 0 fail, 2 skip)

A SKIP is not a pass in disguise: it names the precondition the fort could not meet, and
says when refusing is the correct behaviour. Six cases have turned out to be measuring
something other than the verb — two that could never fail, four that could never pass —
and each was fixed by stating the precondition or correcting the yardstick, never by
weakening the assertion.

Probes: `bonsai-digstat`, `bonsai-digwhy`, `bonsai-dumporders`, `bonsai-mgrdiff`,
`bonsai-plotdump`, `bonsai-entdump`, `bonsai-brewprobe`.

---

## bonsai-reach — can the fort actually get to it?

Not a verb: a module every placing, claiming and digging verb now consults, and a report
you can run by hand.

Almost every silent failure in this project turned out to be a reachability failure
wearing a different hat — designations on sealed rock that produced zero dig jobs, a
shaft whose head nobody could stand on, a farm plot on soil no farmer could walk to, a
workshop placed where nothing was ever reached. Each was found by hand, late, after a
verb had reported success.

**DF already answers it, and cheaply.** `dfhack.maps.getWalkableGroup(pos)` returns a
connectivity id; two tiles are mutually reachable exactly when they share the same
non-zero group, and `canWalkBetween` is that comparison. So the primitive was free all
along and the only real work is asking the right question about the right tile.

**The distinction that makes it useful.** A wall is not walkable, so a tile you intend to
*dig out* correctly reports unreachable — reading that as "digging is broken" cost a day.
So there are two questions, not one:

| you intend to | ask |
|---|---|
| build on / farm / stand there | `tile(x,y,z)` — is the tile itself in a fort group |
| dig out, act on from outside | `adjacent(x,y,z)` — can a citizen stand next to it |

**What it exposes:**

* `group`, `fort_groups` — connectivity, and specifically the groups the fort's own
  citizens stand in. A perfectly walkable island across a chasm is not reachable.
* `tile`, `adjacent`, `building`
* `item` — claimability *and* reachability in one answer, because forbidden, in-job,
  another civilisation's, and behind-a-wall are four different reasons that look
  identical from a count. It also resolves where an item effectively *is*: one in a
  dwarf's pack or the wagon is at its holder's feet, not at the coordinates the item
  struct still carries.
* `site(x, y, z, w, h)` — every tile a free floor a citizen can stand on, returning the
  first tile that fails and why, so a refusal can say more than "no".
* `designations(...)` — how many marked tiles can be worked *now*. A batch that is all
  pending is not wrong (the chamber under a shaft waits for the staircase); a batch that
  stays all pending is an orphan.

**Where it is applied:** `free_material` (reagents), `build_workshop` and
`create_stockpile` (placement), `plantable` (farm siting), and five cases in
`bonsai-toolcheck` — the fort is connected, everything placed can be walked to, the shaft
head can be stood on, some designated tile is workable now, and a claimable reagent is
reachable.

**What it found immediately on the test fort:** 186 designations of which only 32 were
workable, and **14 of 15 barrels belong to another civilisation** — which was indeed part
of why the brewing reaction kept being cancelled, since it needs an empty container.

### The other half: DF says why, in plain language

`world.status.announcements` carries a cancellation line for every job a dwarf picked up
and could not finish. It had been sitting there unread the whole time:

    cancels Brew drink from plant: Needs unrotten plant.
    cancels Carve up/down staircase: Inappropriate dig square.
    cancels Process plants (barrel): Needs unrotten processable (to barrel) plant.
    cancels Hunt for small creature: Interrupted by a tyrannosaurus.

Reachability answers *can we get to it*; this answers *we tried, and here is what was
missing*. `reach.cancellations(limit, filter)` returns them, `bonsai-reach why [filter]`
prints them, and both the default report and `bonsai-toolcheck` summarise the recent
reasons. Three shapes of brew job were called malformed on the strength of a silent
cancellation before anyone thought to read this.

---

## advance

Let the fort run. The only verb that changes nothing by itself.

**Measured, and it matters more than the verb does.** The advance harness used to clear
`world.status.popups` and reset `status.flags.DID_ANNOUNCE` on **every graphic frame**.
DF's fort-level services ride on that machinery, so the fort could not receive migrants
or announcements at all. Our pinned fort sat at 7 citizens across 48,000 ticks with zero
announcements. Clearing popups every ~20 seconds instead:

    citizens        7 → 15 → 18       "Some migrants have arrived."
    announcements   0 → 59            seasons turning, the outpost liaison
    throughput      ~5,000 → ~15,000 ticks per chunk, and it stopped stalling

Every episode measured before that ran in a fort that could not grow. The heartbeat
cannot simply be removed: a modal popup freezes the sim, and plain `pause_state = false`
advanced a fort by ONE tick in four minutes. The cadence has to be coarse enough to leave
the event system alive and frequent enough to unstick the sim. `bonsai-run` does this.

**Still unknown:** the right cadence. 500–2000 frames works; nothing has been swept.

---

## set_labor

Turn a labour on or off for every citizen at once.

**Refuses:** an unrecognised `df.unit_labor` name changes nothing.

**Measured:** `BREWER` off → on flips all 19 citizens and back to 0.

**The thing that surprises people.** Having the labour is not the same as being able to
do the work. On the test fort, 23 citizens carried `MINE` and the fort still dug about
five tiles per 12,000 ticks, because mining needs a **pick** and the fort has three, two
of them lying on the ground. `set_labor MINE true` raises the ceiling to the number of
picks, not to the number of dwarves. The same shape applies to `CUTWOOD` (axes) and
`HUNT` (crossbows) — `EQUIPPED_LABORS` in the catalog exists to let the gate explain
this.

**Still unknown:** nothing here is per-dwarf. A player narrows labours to individuals;
this is a blunt fort-wide switch, and `set_dwarf_labor` is still planned.

---

## designate_dig

Cut a staircase down from a pinned origin and carve a chamber off each landing.

**Refuses:** nothing outright — it designates what it can and reports the count.

### The fourth defect: a designation nobody could reach from the side

Found 2026-08-15 on a fort that had designated rock for 55,000 frames and dug none of it.
Every read agreed the fort was healthy: time advanced, dwarves moved, the reachability
module said the site was reachable, priority was 1000, fifteen dwarves carried the MINE
labour. The job list stayed empty and **DF said nothing at all**, which is the tell:
`world.status.announcements` explains every job DF *cancels*, so silence means no job was
ever created, not that one is pending.

Three things were wrong, in the order they matter:

**A miner cuts a wall from an orthogonally adjacent tile on the SAME z-level.** Not
diagonally, and not from the level above or below. `bonsai-reach`'s general-purpose
`adjacent()` walks six neighbours including z±1, and `dig_site` used it, so open air above
a cliff face counted as a way in. Measured on the stuck fort: of 29 designated tiles, 12
looked reachable by the 6-way test and **0** by the 4-way same-z one.

**`find_site` anchored on `u.pos.z` for every citizen.** Every dwarf was standing on the
surface, so every candidate site was on the surface, and the verb proposed rooms in the
unexplored cliff face twenty tiles from the fort. Replaced by `fort_anchors()`, which
enumerates the tiles a citizen can actually STAND on — walkable group ∈ fort groups —
deepest first, then nearest the fort's centroid, and lays the box against each on all four
sides. Bound it in z as well as x and y: unbounded it asks the pathfinder about half a
million tiles.

**Only one tile needs a way in.** The owner's cascade rule, and it is correct: cutting the
entry tile puts the miner beside the next, so a 4-connected block with a single visible
side entrance excavates entirely. `dig_site` therefore requires one visible entry, one
connected block, and solid wall throughout — and refuses a block split by an air pocket,
because the far half is a separate room the cascade never reaches.

Proved live: 3 tiles designated at 92,112–114 on z=49 with only 92,114 visible and beside
standable ground; all three read `FLOOR` after 6,000 frames, with zero cancellations.

**How it was actually found: by rendering the map and looking at it.** One PNG of z=49
showed a surface camp on a meadow with a single 11×5 chamber below at z=48 — the fort had
never dug in, and the designations sat in undiscovered black. Recipe:

    ./dfhack-run bonsai-map-capture kf /tmp/look.jsonl
    # wrap the line as {"kind":"map","keyframe":true, ...the rest verbatim...}, gzip it
    python tools/replay/render_frame.py live/look.rec.jsonl.gz 49 out.png -1 build
    # crop using the frame's OWN origin, not from 0,0

### Three defects, each of which produced zero excavated tiles

**1. Designating sealed rock.** The original version stamped dig flags on a 5×5×13 block
straight down from a dwarf standing on the surface. The top layer is open air, where a
dig flag is a no-op, and everything below is sealed rock nobody can walk to. A live
ten-day episode excavated exactly zero tiles however many were "designated". Digging in
DF needs **reachability**: every tile must connect to one already reachable.

**2. Setting the tile flag is not enough.** DF only rescans blocks flagged as carrying
new designations. Writing designations through DFHack without
`block.flags.designated = true` produced a perfectly valid staircase that generated ZERO
dig jobs — measured 11 tiles marked, 0 jobs, 0 rock removed over 3,000 ticks, while
`dig-now` on the same designations excavated 35 tiles immediately.

**3. The origin moved.** Citizen[1] wanders, so pinning to its live position started a
fresh one-tile shaft on every call (observed 96,91 then 95,98) — orphaned designations
that connect to nothing. Pinning it in a Lua global fixed that only until the next
reload: the global is per DF process, so after a save/load the origin re-pinned to
wherever citizen[1] stood and the fort started a **second** orphan shaft, stranding the
first one's designations. Measured on a reloaded year-3 fort: shaft head 73,44 while
every outstanding dig job sat around 104,83. It now **recovers the origin from the map**
— if the fort has a carved stairway, that is the shaft — which is in the save and
survives reloads. Verified: clearing the process pin re-pinned to 104,83,49, the original.

### It carves a chamber, not a corridor

It used to cut four one-tile arms at radii 1..3 off each landing. Connected, diggable and
useless: nothing needing floor area ever fits, which is why `build_farm_plot 3 3` refused
while the fort had plenty of dug tiles, every one a single tile wide. It now carves a
solid `len × wide` room (default 4×3) hanging off the shaft, its first column adjacent to
the stair so every tile stays reachable, rotating sides on successive calls so the fort
grows instead of re-designating.

### Reading the state without fooling yourself

Two probe mistakes, both of which made a working fort look broken:

* **`reachable = false` on an undug wall is normal**, not a diagnosis. You cannot walk
  into rock. What matters is whether the tile above or beside it can be reached, which is
  what the staircase provides.
* **A designation that has become a job reads `dig = No`** while the tile is still a wall,
  and a probe matching only job names containing `Dig` misses the shaft entirely, because
  a staircase is cut by `CarveDownwardStaircase` and `CarveUpDownStaircase`. Counting
  designations alone made a fort that was busily digging look stalled at a fixed number
  for four rounds running.

Read together they produced a confident wrong conclusion — "digging has stopped" — when
the shaft was in fact carved to z=48 and cutting z=47.

### Order matters, and DF is right about it

Tiles one level down are **unreachable until the staircase above them is carved**, and DF
says so plainly — `reachable=false` on every one. So a fresh batch of designations looks
inert for a while. That is not a bug, and chasing it produced a **refuted** hypothesis
worth recording: every pick on our fort carries `item.flags.foreign`, another
civilisation's property, which dwarves will not claim. It looked like a complete
explanation for dig jobs that never get a worker. Clearing it changed nothing — 14 dig
jobs, 23 miners, still zero workers. `foreign` is not even abnormal: the hand-played fort
is 13% foreign items, which is what a few years of caravans looks like.

### Where the soil is

A chamber below the soil grows nothing without being muddied first. Measured on the test
fort around the shaft head:

    z=49  surface: GRASS, SOIL, STONE, open air
    z=48  SOIL (and a POOL)
    z=47  SOIL
    z=46  SOIL
    z=45  SOIL
    z=44  MINERAL / STONE  ← soil ends
    below rock

Chambers are cut at `oz-1` downwards, so the first few landings are the farmable ones.

**Still unknown:** throughput is dominated by pick count, and nothing balances the
chamber size against the dig budget.

---

## build_workshop_cluster

Place a related group of workshops and the stockpiles that feed them.

**Refuses:** a cluster name not in the library, a scale with no variant — and, the part
that matters, a cluster ANY of whose members the fort cannot supply. It checks every
member's build filter before placing a single one, and if a placement fails partway it
DECONSTRUCTS what it had. Half a cluster is a failure that looks like success: the
buildings get counted, the capability is not there, and the missing member is usually the
one the rest were built for.

**Measured:** every workshop in the cluster standing with a build job carrying its full
requirement, plus the stockpiles, plus the links.

**Cost is DF's, not a count of members.** Read live from `getFiltersByType`: Siege and the
Ashery cost three items, the forges and the Dyer's and the Millstone two, the other
seventeen one. `Cluster.cost` sums the real table, so `metal` at size 1 costs 3 for two
buildings.

**Capability counts DISTINCT kinds.** Two Carpenter's workshops unlock no new job; they
buy throughput. Counting the member list would make size and capability the same number
and the agent would be choosing on one thing twice. The per-building figures are DFHack's
own `getJobs` — and they are WORLD-SPECIFIC, which is written down where they live: it
appends one `SmeltOre` per ore-bearing inorganic (16 in this world), and the Craftsdwarf's
631 is one job kind repeated per instrument and per material.

**What it cannot be built without.** `Cluster.needs` carries the demands that are not
"any building material" — a manufactured QUERN item, a MILLSTONE plus TRAPPARTS, an ANVIL,
an EMPTY barrel — and `Cluster.prereq` names the buildings that have to exist first, off
the same measured table. `milling` is the case that proves both: three of its four members
cost items no fort has at embark.

**Both sides of every link.** A stockpile carries `links` directly; a workshop does NOT —
its four vectors live at `profile.links`, enumerated live. Writing only one side is this
project's signature bug and has already cost it the noble seat and the room owner.

**It sends the workers.** `building.profile.permitted_workers` is what DF's own Workers
tab edits, established causally: two identical Carpenters restricted to different dwarves,
the assignment swapped, and the working dwarf swapped with it three times out of three.
Written with `utils.insert_sorted` and NOT `insert('#', id)` — DF scans the vector linearly
and honours an unsorted list, but DFHack's binsearch then denies an id that is physically
there, so our own read-back would lie. There is no back-reference: `df.unit` has only
`owned_buildings`, which is rooms, so here the one-sided link is correct by design.

**The labour guard is the one that matters.** A master who lacks the shop's labour makes
the job sit forever with NO announcement — measured at 2,760 frames of `WORKER=none`,
then one labour bit flipped and the same dwarf took it within 540. So
`#permitted_workers > 0` is a worthless assertion and the battery checks the master can do
the work. A recommended build-stage guard was WRONG and would have made the feature
useless: every shop a cluster places is unbuilt at that moment. Measured — the name sticks
at stage 0/3 and binsearch finds it.

**It is packed, not scattered.** The whole cluster takes ONE contiguous site: workshops
edge to edge in a row, stockpiles in a two-deep band flush underneath. The link does
nothing for distance — it only constrains which items are candidates — so a pile ten tiles
away is ten tiles of hauling forever, and the previous version left them 9, 10 and 10
tiles out with its two shops 10 apart. DFHack's own blueprints are the yardstick:
embark.csv abuts a 15-wide pile slab against a 15-wide shop row at gap 0, and dreamfort's
industry level has 25 of 28 workshops with a stockpile tile at gap 0. Measured after:
worst distance from a pile to its nearest shop = 0.

---

## ensure_furniture — a request unfolds into its own prerequisites

`ensure_furniture  c:1,d:1,t:1` — "these pieces must exist", resolved all the way down and
executed in the SAME call.

The owner's requirement:

    вся эта цепочка из требований должна раскрываться и автоматически резолвится

Placing an office is not one action. It is a chair, a table and a door; those are three
items nobody has made; making them needs a Carpenter's workshop; building that needs a log;
getting a log needs a tree felled. Running that chain by hand proves the mechanics and is
precisely what a player never does — DF's own build menu will not offer a bed that does not
exist, so the REQUEST has to be the thing that unfolds.

**The dispatcher is a queue, not a file scan.** `need()` splices a prerequisite in ahead of
whatever is still pending, so the closure runs in dependency order inside one request. The
insertion cursor matters: splicing every prerequisite at the same index reverses them, and
the chain would try to build a workshop before there is a log to build it from.

**It terminates at what the world gives directly** — trees (`chop_trees`) and rock
(`designate_dig`). Everything else is a workshop plus a reagent, read off `JOB_SPEC`.

**It does not redo what is done.** Variants are preferred in the order: workshop already
built AND reagent in stock (costs nothing) → workshop built → first variant, building down
to it. A per-call `RESOLVED` set stops a design that wants a chair and a table from ordering
two carpenters and felling the forest twice.

Measured live on a fort with 332 logs, one built Carpenter's and no Masons:

    ensure_furniture  s:1,b:2
    RESOLVED 4 prerequisite(s):
      - dig for 1 stone
      - build a Masons
      - ConstructStatue x1 from stone at the Masons
      - ConstructBed x2 from wood at the Carpenters
    APPLY ... add_workorder=2 build_workshop=1 designate_dig=30 ensure_furniture=1

The stone request deliberately opens more than three tiles. A clean embark can have a
soil cap, and mined rock does not yield a boulder on every tile. The old three-tile leaf
built the Masons from the only available material and left the statue order armed forever.

Clean DF 53.16 control, from frame 0 with seven citizens and no logs, boulders or
workshops, using the external `bonsai-run-loop.sh` (5,000-frame chunks and paused pump
visits): the single request `ensure_furniture s:1,b:2` finished at frame 40,000 with a
built Masons, a built Carpenters, `BED=2`, `STATUE=1`, five spare boulders and 105 free
logs. The durable ledger was zero bytes and the pump reported `orders=0`, `error=nil`.
The shaft crossed five soil levels, repaired DF's cancelled next-stair designation, and
cut its ordinary chamber tiles deepest-first so the batch reached actual stone.

The outer loop is intentional. DF accepts scanner wakeups from frame callbacks, but live
tests showed workshop job creation returning zero from that callback context despite
built shops and free reagents. `bonsai-run-loop.sh` therefore alternates simulation with
an evaluator-side paused `bonsai-apply-actions <same-file> pump`; pump mode keeps the same
ledger but does not reread or restate the original intent.

Note what it did NOT do: no felling (logs existed) and no second Carpenter's.

**The deferred half is DFHack's `buildingplan`,** which quickfort already routes `#build`
through. A `#build` section on a fort with no furniture leaves the pieces at stage 0/1
marked PLANNED, and they resolve by themselves the moment the items exist — measured on the
office at 92,112–114: Chair/Table/Door went PLANNED → `stage=1/1` with no further request.

**Where the stamp lives.** `apply_template` runs twice per design — the dig, then the zone
and furniture — and the second call must land on the first one's site. That memory used to
be a Lua global; a global survives between `dfhack-run` calls but dies with the process, and
when the scratch DF died mid-test the fort came back with a dug room nobody could name. It
is now `dfhack.persistent.saveSiteData('bonsai/stamped', ...)`, which is written into the
save with the fort — the owner's point that the marker has to be in the GAME, not only in
our own head.

**Open:** running the `rooms` stage twice stamps a SECOND civzone on the same tiles (two
Office zones at 92,112..113, values 34 and 34). Harmless to the fort, wrong as accounting.

## apply_template

Stamp one of DFHack's shipped room designs — dig, build and zone in one intent.

**Refuses:** a template name not in the library, and — the part that matters — a fort with
nowhere the design fits. It walks a ring asking `bonsai-reach.site` whether every tile of
the blueprint's measured extent is a floor a citizen can stand on, and declines rather
than stamping a 47x47 crypt into solid rock.

**Measured:** designations and buildings inside the template's own box, counted before and
after. quickfort prints its own `Tiles designated for digging: 83` and that line is not
evidence — it is what quickfort intended, and this project has been burned by intent
before.

**The position trap, and it is the whole thing.** quickfort's CLI lands the cursor on the
blueprint's own `start()` cell, NOT on its top-left corner. `library/tombs/Mini_Saracen.csv`
declares `start(6;6)`; run at `-c 100,90,45` on the live fort it put designations in the
box **95,85 .. 105,95**, exactly six-minus-one back and up. The `apply_blueprint` API does
the opposite — it adds the position to the data indices and ignores `start()` entirely —
so the two entry points disagree by the anchor, silently.

**Addressed as `library/<path>`.** The files sit at `hack/data/blueprints/<path>` on disk,
but quickfort wants the library name. Handing it the disk-relative path gets
`failed to open "dfhack-config/blueprints/tombs/Mini_Saracen.csv"`, which reads like a
missing file rather than a wrong prefix.

**The library lives in python, not here.** The gate expands a template name into the
quickfort name, the measured extent and the anchor, so the DFHack side holds no second
copy of the table to drift from the first. What it receives it does.

**No tier argument.** The planned signature had one, aimed at a quality tier. v50's
quality cutoffs are not knowable on this build — `getRoomDescription` is the stub — so a
number the game will never confirm has no business in the contract. See
`bonsai-roomvalue` and `buildings_plan.md`.

**Still unknown:** every extent is the largest single z-level, and `levels` is carried but
not yet used to check the fort has that much depth below the site. `pump_stack` reports
one level because its repetition lives in a `#meta` section, which understates it.

---

## build_room

Build one generated room as a durable workflow instead of asking the controller to
remember a multi-hour sequence of atomic calls. A stable `request_id` is the identity of
the intent; repeating it resumes the same coordinates and never means "build another".

**Rock strategy:** require one visible, orthogonally reachable face and a single connected
block of hard natural wall; stamp `dig`, wait for the expected floor count and zero pending
designations, stamp `smooth`, then create the zone and furniture. Soil is refused for a
design that banks smoothing value. `auto` falls back to the surface strategy when no legal
hard-rock site exists.

**Surface strategy:** require an empty reachable rectangle of open floor, plan a real
constructed shell (`Cw` walls and `Cf` floors) through buildingplan, unfold missing blocks
through stone, a Mason's and `ConstructBlocks`, then create the zone and furniture only
after the shell exists.

**Refuses or waits:** unsafe request ids, shipped templates with no room contract, no legal
site, missing role holder, unreachable finished interiors, resource chains still in
progress, value below the archived demand, or more than one matching civzone. It does not
delete a duplicate zone automatically because choosing which player object to destroy is
not a safe recovery.

**Acceptance receipt:** exactly one active civzone at the stored extent; every required
furniture building at full build stage; the bidirectional owner link in
`unit.owned_buildings`; a reachable interior tile; and `bonsai-roomvalue` at least the
design's live noble demand. Workflow records live in `bonsai/room-workflows-v1` site data
and are revisited by evaluator-side `pump` calls after save or client restart.

---

## create_stockpile

Place a 2×2 stockpile on a ring around the wagon.

**Refuses:** nothing at the verb level — the count is clamped to 1..8 at the gate and the
verb places what it can. The one thing it will not do is claim a placement that did not
happen: the count only rises when `constructBuilding` returns a building.

**Measured:** 0 → 1 buildings of type Stockpile, and the new pile accepts 17 of 17
categories with 343 real stone materials in its list.

**It walks the ring until a placement takes**, the same way `build_workshop` does. A
single attempt worked on an empty embark and silently placed nothing once the ring
filled: measured on a fort with three stockpiles, `create_stockpile 1` reported 3 → 3.

**A pile that exists is not a pile that works — and for weeks these did not.** The verb
placed an UNTYPED stockpile: every accept flag false, every per-category material vector
at length 0. DF matches items against those vectors, so the pile accepted nothing, DF
generated no hauling job, and the test fort's wagon was still fully loaded three game days
after embark with all 54 embark goods reading "another civilisation owns it". The battery
counted piles and passed the whole time. The catalog note said it "accepts the default
everything", which was the opposite of the truth.

**How it is set now, and why not by hand.** DFHack ships the complete per-category
settings as `.dfstock` presets in `hack/data/stockpiles`, and its own quickfort applies
them through `plugins.stockpiles.import_settings`. Importing `library/cat_stone` sets
`flags.stone` AND fills `stone.mats` — verified live, 0 → 343, with an un-imported
category left at 0 as the control. Writing those vectors ourselves would mean guessing
their sizes out of the raws.

**The modes do not do what their names suggest.** Measured on a pile accepting all 17
categories: `enable` adds one; `set` replaces wholesale (17 → 1, `stone.mats` 343 → 0);
**`disable` did nothing at all** — 17 categories before, 17 after. The first draft of the
narrowing path disabled all seventeen and then enabled one, and reported success while
changing nothing.

**Naming a category is the player's move.** `create_stockpile 2 food` places two food
piles, the way DF's own UI makes you pick a type from a menu. Omitting it means
everything. An unknown category is refused, not substituted.

**How far this is proved, and how far it is not.** The settings are now identical to what
DFHack's own quickfort produces, and DF's `getStockpileContents` answers **25, 4 and 4**
for the three preset-configured piles against **0 and 0** for two piles whose flags were
set by hand with the material vectors left empty — the differential the fix predicts.
What is NOT observed is a `StoreItemInStockpile` job appearing, and the test fort cannot
settle that: it is down to six citizens under constant `Interrupted by a tyrannosaurus
man` cancellations, with both idle dwarves on break. Re-check on a fort that is not under
attack before calling the hauling path proved.

---

## build_workshop

Build a workshop on a ring around the wagon.

**Refuses:** an unknown `df.workshop_type` name, AND a workshop whose material the fort
has not got. DF states each building's real requirement through `getFiltersByType`: a
Quern wants a manufactured QUERN item, a Millstone a MILLSTONE plus TRAPPARTS, the forges
an ANVIL, the Ashery BLOCKS plus an empty barrel plus a bucket, Siege three materials. The
verb passes those FILTERS so DF records the requirement and picks the items itself.
Handing a Quern a log does not fail loudly — DFHack builds the job from whatever you pass,
so the job carries a reagent and any "has an item" guard fires. Measured: Carpenters
0 → 1, and Quern, Millstone, MetalsmithsForge and Ashery all 0 → 0 on a fort with none of
those items and only wood, which burns.

It used to fall back to Carpenters for an unknown name — the
same silent-substitution shape that turned `add_workorder NoSuchJobType 5` into five beds
— so an agent asking for a Still got a carpenter and the brewing it was planning quietly
never happened.

**Measured:** `Still` 1 → 2; `NoSuchWorkshop` leaves the Carpenters count unchanged.

**It tries more than one spot now.** Placement walks a ring around the wagon, and one
attempt was enough on an empty embark and silently did nothing once the ring filled:
measured on a fort with eight workshops, `build_workshop Still` reported success zero
times while sixteen logs sat free. It tries twelve positions before giving up, which is
what a player does — look somewhere else.

**The trap underneath.** `constructBuilding` with no `items` produces a building whose
ConstructBuilding job has no reagent; DF cancels the job and drops the building, and the
caller sees a perfectly successful return value. Measured live: build_workshop reported
success and `world.buildings.all` held nothing but the wagon 20,000 ticks later, while
the identical call WITH a log attached built the workshop. So it claims a reagent up
front and only counts a build when a job with items is actually attached.

Two further traps in choosing that reagent: a workshop is **made of** its log, and handing
that same log to a job destroys the workshop (shops went 1 → 0 the moment a bed job
claimed a reagent); but excluding everything held by a building is far too broad, because
at embark every supply sits inside the **wagon**, which is also a building. So it asks
who holds the item and accepts wagon-held goods.

---

## assign_noble

Put a dwarf in an administrative position.

**Refuses:** a position code the fortress entity does not have.

**Measured:** MANAGER seated, `histfig2 == histfig`, `never_cull` set.

### Two halves of a two-sided link, and DF reads the other one

Writing `entity_position_assignment.histfig` is the obvious move and it is a silent
no-op. The screen field went -1 → 1741 and `getNoblePositions` still returned nothing,
because DF and DFHack both answer "who holds this office?" by walking the **histfig's**
`entity_links` for a `histfig_entity_link_positionst`. MANAGER, BOOKKEEPER and the rest
are SITE positions on the fortress entity; `make-monarch.lua` uses the CIV entity because
MONARCH is a civ position, and copying it verbatim seats nobody.

Even with the link, DF would not accept the officeholder. The difference, found by
running our fort and a hand-played 119-dwarf fort side by side and transplanting our
seating code onto the working one:

| what our code wrote | result |
|---|---|
| `histfig` + the POSITION link | `plotinfo.nobles.manager_cooldown` stayed 0 — DF finds nobody |
| ...plus `histfig2 = histfig` and `hf.flags.never_cull` | cooldown reloaded to 1008 |

Every position DF had appointed itself carried `histfig2 == histfig`; the ones our code
appointed carried `-1`.

**The picker had a second defect.** `pick_best` ranks by skill and had chosen a dwarf who
was **in a military squad**, which DF refuses for an office. Seating a squad-free citizen
on the same fort woke the cooldown within 70 ticks. Reassigning a seat also strips the
POSITION link the previous holder still carries, or two figures claim one seat and DF's
lookup — which walks links, not the assignment — can pick the stale one.

**What is NOT required, measured rather than assumed:** an office. The hand-played fort's
working manager owns a bedroom and nothing else, and removing the previous manager's
office ownership did not stop the cooldown either. Population is not required either:
that was "refuted" once on a miscount (the line printed `#world.units.active`, which was
mostly troglodytes and storks; real `getCitizens` said 7) and then properly refuted at
36 real citizens.

**Still unknown:** why the manager duty never fires on our forts even when seated
correctly. `manager_cooldown` decrements at the normal 1 per 10 ticks and then fails its
check at 0. Population, office, world age, squad membership, order shape, fort rank,
`save_progress`, site links and the embark procedure are all eliminated — including on a
fort DF built itself, through the embark screen's "Start tutorial" button, in a 250-year
world. See `workorder_contract.md`.

---

## add_workorder

Make a specific quantity of something, once.

**Refuses:** any job outside `ORDERABLE_JOBS`. The list is closed at the gate as well as
in Lua, because an open list fails silently: `add_workorder NoSuchJobType 5` used to fall
through to a default and queue five ConstructBed jobs. `MakeBarrel` is in the list and
`ConstructBarrel` is not, because the latter was invented from memory and `df.job_type`
has never had it.

**Deliberately without a condition or a schedule** — that is `add_workorder_conditional`,
a different thing to want even though DF stores both in one `manager_order`. See
`open_decisions.md`.

### Material follows the job, and the wrong one is not a soft failure

`material_category` used to be hardcoded to wood for every job, and the reagent picker
took wood-or-stone whichever it found first — so a bed order could be handed a boulder
once the logs ran out. DF cancels that job thousands of ticks later, with the order's
count already spent on it. Each job now names its (material, workshop, reagent) variants,
and `shop_for` returns nil rather than a fallback: it used to read
`return want and nil or fallback`, which evaluates to `fallback` in **every** branch, so a
brew order would have gone to the carpenter exactly as its comment promised it would not.

### Who owns the count

DF does, and it retires an order sooner than you would expect. Sampling an order every
200 frames while its jobs completed:

    order 6, five jobs queued     left = 6
    ...as each job finished       6 → 5 → 4 → 3 → 2 → 1
    last queued job done          order GONE, with left = 1

So `amount_left` is spent on completion — decrementing at issue time as well double-counted
every job — and **an order is retired as soon as the jobs queued against it are gone,
whatever the count says.** On a normal fort DF's own dispatcher tops the queue back up
first; on ours it never runs, so everything past one workshop-load was silently dropped:
a request for twelve beds delivered five and closed itself claiming to be done.

Ownership is therefore inverted. `_G.BONSAI_ORDERS` is the ledger of what was asked for
and not received; each `df.manager_order` mirrors **one batch** — exactly the jobs queued
for it — so DF's count and its retirement are both correct. Measured end to end: 12
requested, beds 25 → 30 → 35 → 37 over three dispatches, owed 12 → 7 → 2 → 0, then flat.

**The ledger is now on disk too**, beside the actions file as `<actions>.orders`, one
tab-separated line per order. A Lua global dies with the DF process, so a mid-episode
restart — a crash, a watchdog, a reload to inspect something — used to take the
outstanding remainder with it silently: the agent had asked for twelve beds, five were
queued, and the other seven simply stopped existing. Verified by wiping the in-memory
ledger and dispatching again: 12 requested, 3 queued, 9 written, 9 recovered.

**Still unknown:** the ledger is keyed to the actions file path, so two episodes sharing
one path would share one ledger. They are per-episode today, but nothing enforces it.

---

## add_workorder_conditional

Watch a stock level and refill it automatically.

**Refuses:** a job outside `ORDERABLE_JOBS`, an item type DF does not know, and a
comparison or frequency it does not recognise falls back to `LessThan` / `Daily`.

### The shape came off a hand-played fort, not off intuition

    #398 MakeAsh  x5/10  Daily  val=true act=true
         WHILE LessThan 10 of BAR (ASH)

Thirty of that fort's fifty-seven orders carry a condition and every one of those is
Daily. Three things that shape corrected:

* **The amount is the FULL order** (ten ash), not the shortfall. The condition is what
  stops it — once ash reaches ten, `LessThan 10` is false. The first implementation
  ordered `min(batch, below - have)`, which is not a thing DF does.
* **`status.active` means "the condition holds right now"**, not "we approved it". That
  fort carries `#299 SmeltOre val=true act=false` — validated and idle for want of gold
  ore. Forcing `active` erases exactly the bit that expresses the condition.
* **A condition names a material** — `BAR (ASH)`, not any bar — so the stock count filters
  by material and the condition is written into the order's real `item_conditions`. It
  reads in-game and exports through `orders export` like a player's.

**Measured:** fires when stock is below the threshold and stays silent when above; orders
the full amount; the daily schedule holds it back on an immediate re-dispatch and lets it
through once a game day has passed (2 jobs on day 0, 2 more after 1,500 ticks). Restating
an order re-checks it at once rather than waiting out the old schedule.

**Frequency is real game time:** Daily 1200 ticks, Monthly 33600, Seasonally 100800,
Yearly 403200, off an absolute tick so it survives the year boundary.

**Still unknown:** DF's other condition dimensions are not reachable through these
arguments — item flags (`cookable`, `unrotten` on a real `PrepareMeal` order) and
dependencies on another order finishing (`order_conditions`).

---

## build_farm_plot

Lay out a farm plot on ground that suits the crop you mean to grow.

**Refuses:** a plant that does not exist; and any site where the intended crop would not
grow. If nothing suitable is dug out, the count stays at zero and that refusal is the
useful output — it points at `designate_dig`.

**Which ground is right depends on WHAT is being planted.** A subterranean crop in a
surface plot grows nothing while the plot reads as built and sown, and the first version
did exactly that: it built outdoors and sowed plump helmet. That embark happened to ship
six crops that were all `BIOME_SUBTERRANEAN_WATER` — plump helmet, cave wheat, pig tail,
sweet pod, dimple cup, quarry bush — but an embark carrying wheat or another surface
plant wants the opposite ground, so the rule is the crop's, not the species'. The crop is
chosen first and the site demanded to match, falling through the fort's other seeds
rather than building somewhere nothing will grow.

The search runs **down** from the citizen's level as well as across it: dug-out soil is
under the embark, and an earlier pass scanned only the dwarf's own z and found nothing
while 165 usable tiles sat a few levels below.

A plot takes no items to build, so it is finished outright rather than left waiting on a
construction job that carries no reagent, and it is sown on the spot with the crop its
ground was chosen for.

**Measured:** `NO_SUCH_PLANT` refused; `MUSHROOM_CUP_DIMPLE` built at z=49
`outside=false` and sown with dimple cup; `3 3` refused for want of a chamber that size.

**Still unknown:** irrigation. Muddied rock farms too, and nothing here can muddy it, so
the fort is limited to natural soil.

---

## set_crop

Choose what the farm plots grow, per season.

**Refuses:** a plant that does not exist. `best` picks **per plot**, matched to where that
plot is, preferring a crop that can be brewed because drink is what a fort runs out of
first.

**Measured:** every plot on the test fort ends up sown with a crop whose biome matches its
location — the battery asserts this, because sowing the wrong one is invisible.

**Still unknown:** it sets every plot. There is no way to address one plot, and no
per-season planning beyond "all" or one season index.

---

## set_kitchen_flag

Forbid or allow cooking an item type, for every material the fort holds.

**Refuses:** an item type DF does not know.

**Reports reaching the requested state, not only changing it.** DF ships with seeds
already excluded from cooking, so a correct `set_kitchen_flag SEEDS false` looked like a
failed verb until this was fixed.

**Why it matters out of proportion to its size:** cooking destroys seeds, and cooking
drink turns the beer supply into meals. It is pure downside protection and the guide's
most emphasised early setting.

**Still unknown:** it only touches the cookery exclusion (`exc_type` 0). Brewing and seed
use have their own exclusion types and are not reachable, and it works per item type
across all materials rather than per material.

---

## brew_drink

Queue the real DF 53.16 brewing reaction at a built Still. It remains deliberately
absent from generic `ORDERABLE_JOBS` because there is no `BrewDrink` job type.

**1. There is no `BrewDrink` job type.** Not on this build — nothing in `df.job_type`
matches `brew` at all. That is the third enum name written from memory that turned out not
to exist, after `ConstructBarrel` (it is `MakeBarrel`) and a workshop kind that silently
became Carpenters, which is why `bonsai-toolcheck` now asserts every name in `JOB_SPEC`
resolves.

**2. Brewing is a REACTION.** The raws carry `BREW_DRINK_FROM_PLANT` (index 135) and
`BREW_DRINK_FROM_PLANT_GROWTH` (136) among 1,109 reactions. That is also why several of
the hand-played fort's food orders read `CustomReaction` rather than a named job. Plump
helmet's structural material lists `DRINK_MAT` and `SEED_MAT` as its reaction products,
so the staple crop does brew.

**3. DF does not fill `job_items` in for us.** A job created bare at a Still is cancelled
— measured twice. The requirements have to be written by us. This is worth stating plainly
because furniture jobs work *either* way: a pinned item and a specification both produce a
bed, which made it look as though DF was doing the work.

**4. The job shape is RIGHT; the reagents were not.** Three shapes were tried and the
first two were genuinely wrong, but the third was not, and reading DF's own cancellation
line is what separated them:

| attempt | what DF said |
|---|---|
| `ProcessPlantsBarrel` at a Still, bare | cancelled — no job_items at all |
| `ProcessPlantsBarrel` at a Still, with a derived spec | cancelled — `Needs unrotten processable (to barrel) plant` |
| `CustomReaction` + `reaction_name = BREW_DRINK_FROM_PLANT`, reagents copied from the reaction | **survives**, a dwarf takes it, then `cancels Brew drink from plant: Needs unrotten plant` |

So the third form is a real, valid brewing job — DF names it "Brew drink from plant", a
dwarf picks it up, and the specs read back correctly:

    need type=PLANT sub=-1 mat=-1:-1 qty=1 flags=[unrotten]
    need type=NONE  sub=-1 mat=-1:-1 qty=1 flags=[empty,food_storage]

Two things had to be true before it got that far, and both were invisible until
`bonsai-reach` was written: there must be an **empty container the fort owns** (14 of the
fort's 15 barrels belong to another civilisation), and there must be a plant DF accepts.

**What closed the gap.** A real farm-grown plump helmet satisfied the same job where a
synthesised plant did not; played live, drink moved `0 -> 1`. The shipped action therefore
copies the reaction raw's own requirements and never invents a reagent filter.

**Refuses:** no built Still, no `BREW_DRINK_FROM_PLANT` raw, or an incomplete reagent
copy. It prints the reason into the action receipt. Missing/unreachable plants or empty
owned barrels remain game-state failures: DF reports those cancellation reasons, the
observer exposes the corresponding stock and active brew-job count, and a controller can
correct the dependency on its next round. Repeating the action is idempotent up to its
bounded target; existing live brewing jobs are counted rather than duplicated.

`bonsai-brewprobe` remains the focused diagnostic for the raw reaction/job shape.

---

## create_zone

Paint a zone: bedroom, dining hall, meeting area, pen, office, plant gathering, dormitory,
refuse dump, barracks or tomb. A dug room is not a bedroom until something says so.

**Refuses:** a zone kind not in the list, and any site where the rectangle is not entirely
free, walkable floor a citizen can reach — it walks a ring of candidate spots and gives up
rather than painting a zone in rock.

**The enum trap.** `civzone_type` runs to 97 on this build and the player-facing zones live
at the **top** of it: Bedroom is 92, DiningHall 80, MeetingHall 87, Pen 88, Office 93. The
low end is worldgen site vocabulary — Home, MeadHall, ThroneRoom, forty kinds of workshop
pit — and picking one of those produces a zone the fort never uses. Enumerated live rather
than remembered, after three enum names written from memory turned out not to exist.

**Three things DFHack treats as optional and DF treats as fatal**, all found the hard way
while building the manager an office:

* `abstract = true`, or `constructBuilding` simply fails
* extents cast through `df.reinterpret_cast(df.building_extents_type, ...)` — a raw
  `uint8_t` array assigned afterwards silently does not take
* `spec_sub_flag.active`, without which the zone exists and does nothing

**Measured:** Bedroom, DiningHall and MeetingHall all created on a live fort.

**Still unknown:** it places on a ring around the wagon rather than inside a room you dug
for it. Pairing a zone with a specific chamber is what `apply_template` is for.

---

## assign_room

Give a room to a dwarf. An unowned bedroom is furniture in a hole.

**Refuses:** a room kind that does not exist, and a dwarf id that is not a citizen.
Without an id it picks a citizen who does not already own a room.

**The trap:** `dfhack.buildings.setOwner` early-returns `true` when the zone already names
that unit, so writing `assigned_unit_id` first makes the call a no-op that reports success
while `owned_buildings` stays empty. The same one-sided-link shape as seating a noble with
`histfig` but no entity link. Ownership is confirmed by reading the dwarf's
`owned_buildings` back, not by trusting the return value.

**Measured:** a bedroom assigned on a live fort, confirmed through `owned_buildings`.

---

## place_furniture

Install something already made: bed, table, chair, door, cabinet, coffer or coffin.

**Refuses:** a furniture kind not in the list; and it will not invent the item — this verb
puts a bed down, it does not build one. `add_workorder ConstructBed` makes the item first.

**Measured:** two beds installed on a live fort out of 44 free bed items.

**Two traps it inherits from build_workshop.** A build only counts when DF actually
attached a job carrying a reagent — `constructBuilding` returns a building even when DF is
about to cancel and remove it. And the item must be free: `flags.in_building` distinguishes
the item a building *is* from stock it merely holds, which is why a filter that rejected
everything held by a building could not find the chair a workshop had just produced.

**Still unknown:** placement is a ring around the wagon, not "in that bedroom". Furniture
lands where there is room, and the zone it ends up in is luck.

---

## set_dwarf_labor

One dwarf, one labour. `set_labor` is a fort-wide switch; a player specialises.

**Refuses:** an unrecognised `df.unit_labor` name, and a dwarf id that is not a citizen.

**Measured:** `CARPENTER` set on a single citizen without touching the rest.

**Still unknown:** the guide's actual move is to pull a dwarf *out of the general pool* so
they only do their speciality — that is a different operation from enabling one labour, and
it is not expressible yet.

---

## cancel_dwarf_job

Drop one dwarf's current job so somebody else can take it, or so they can do something
that matters more.

**Refuses:** a dwarf who is not a citizen, and one who is idle — there is nothing to
cancel, and reporting a cancellation that did not happen is the failure mode this whole
toolkit is built against.

**Why it earns a verb:** DF cancels jobs constantly for reasons it writes down —
`Interrupted by a tyrannosaurus`, `Hunting vermin for food` — and a fort can sit with
every dwarf busy on something trivial. See `bonsai-reach why`.

---

## configure_stockpile

Say what a pile accepts. Addressed by index, so a fort with several can narrow them
differently.

**Refuses:** a category outside the list DFHack ships a preset for — ammo, animals, armor,
bars_blocks, cloth, coins, corpses, finished_goods, food, furniture, gems, leather, refuse,
sheets, stone, weapons, wood. `drink`, `sheet`, `bars`, `blocks`, `goods`, `ore` and `misc`
are accepted as aliases onto those. Note the preset is spelled **sheets** where the
settings flag is spelled **sheet**; they are not interchangeable.

**Measured:** food=true, stone=false, 1 of 17 categories on, and `food.meat` accepting
20644 materials — the flag AND the list, because DF matches on the list.

**It reported success and did nothing, for as long as it has existed.** The old body
walked `settings[<group>]` flipping any boolean it found. Those groups hold VECTORS, so it
flipped almost nothing, and it never touched `settings.flags` at all. Measured on three
configured piles: every flag still false, every material vector still empty.

**Why it matters more than it looks.** The guide's first act on a new pile is to NARROW
it — removing stone and wood so bulk goods cannot crowd out perishables — and it has three
separate fort-saving uses: a seeds pile with barrels OFF so dwarves can find the seeds, a
refuse pile so corpses leave the fort, and a starter pile with stone and wood excluded.

**Narrowing is DFHack's `set` mode**, chosen by measurement rather than by name: `disable`
turned out to be a no-op on a whole category, while `set` took a pile from 17 categories
to 1 and `stone.mats` from 343 to 0.

**Containers live on `storage`**, not on the building and not in `settings` — enumerated
live, because the first draft wrote `target.max_barrels`, which is not a field and would
have failed silently inside a `pcall`. `containers False` sets `storage.max_barrels` and
`max_bins` to 0, which is the guide's seed-pile trick.

**Still unknown:** it is one category per call, all-or-nothing within that category. DF's
settings are per-subtype (food → seeds, drink, meat…) and nothing here reaches that far.

---

## chop_trees

Mark surface trees for felling.

**Refuses:** a tile that is not a tree, one already designated, and — since it consults
`bonsai-reach` — one nothing can stand next to. Felling uses the same designation field as
digging, set on a tile whose material is `TREE`, and needs the block's `designated` flag
like every other designation.

**Measured:** 8 trees marked on a live fort, out of 21 within twenty tiles.

**Why it matters:** wood is the fort's first material and it runs out. Beds, barrels,
doors and the constructed walls that seal a breach all come from it, and an embark brings
about a dozen logs.

**Still unknown:** it takes the nearest trees rather than a chosen stand, and nothing stops
it clear-cutting the entrance.

---

## smooth

Smooth dug stone.

**Refuses:** anything that is not stone or mineral, anything already smoothed, and
anything unreachable.

**Measured:** 20 tiles marked on a live fort.

**Why it earns a verb:** it does double duty — it raises a room's value, which is what
makes a bedroom worth having, and it is the cheap way through an aquifer because a smoothed
wall stops seeping.

**Still unknown:** engraving is the second half (`smooth = 2`) and is not exposed, and
there is no way to smooth *a room* rather than a radius.

---

## build_construction

Build a wall, floor, ramp or staircase out of stored material.

**Refuses:** a construction type outside DF's own list (Fortification, Wall, Floor,
UpStair, DownStair, UpDownStair, Ramp and the track pieces), a site nothing can reach, and
a fort with no free stone or wood — it claims a reagent up front, like `build_workshop`,
because a construction job without one is cancelled and removed.

**Measured:** 2 floors placed on a live fort.

**Why it matters:** it is how a fort makes space it did not dig and seals what it did, and
it is half the standard aquifer technique.

---

## set_standing_order

Flip one of DF's fifty fort-wide policies.

**Refuses:** a name that is not one of the `df.global.standing_orders_*` globals — there
are exactly 50 and they are enumerated live, not remembered.

**Measured:** `gather_refuse_outside` turned off on a live fort.

**Why the guide singles this one out:** leave refuse collection on and dwarves haul rotting
vermin indoors past the food; turn it off and the surface becomes a rubbish tip. It is
policy, not an action, and it is the kind of thing a fort lives or dies by without anyone
noticing it was set.

**Still unknown:** the fifty are exposed by name with no grouping or explanation, so the
agent has to know which one it wants.

---

## set_dig_priority

Set the priority of mining designations, 1 highest to 7 lowest.

**Refuses:** nothing — it clamps to 1..7 and applies to every outstanding designation
around the shaft, reporting how many tiles it touched.

**I reported this mechanic as absent, and that was wrong.** `map_block` carries
`designation`, `occupancy`, `tiletype` and `walkable` and no priority array, and I
concluded from that one missing field that the build did not support it. The owner said
otherwise, and they were right.

**Where it actually lives.** Not a field on the block but a **block square event** of type
`designation_priority`, indexed by `pos % 16` and stored as `priority * 1000`. Created on
demand if the block has none. This is exactly how DFHack's own `quickfort/dig.lua` writes
it — read the working implementation rather than concluding from an absence.

**Measured:** 185 designated tiles set to priority 2, read back from the game as
`priority=2000` on `DownStair` and `Default` designations alike.

**Why it matters:** at priority 2 dwarves stop wandering off to haul instead of dig, which
on a fort that mines at five tiles per 12,000 ticks is the difference between a chamber
this season and next.

---

## Resetting the scratch fort

The test fort accumulates. After a day of battery runs port 5006 carried 164 buildings,
700+ dig designations and farm plots from before the crop rule existed — and three separate
red lines that session turned out to be that state rather than the code. Reset it when the
placement cases start skipping for want of room.

Nothing is written to disk unless DF saves, so a reload restores the fort exactly.

    # 1. reboot the 53.16 build on the scratch port. It kills only that port's DF; the
    #    supervised fort on 5000 is never touched, and boot16.sh checks that.
    bash /srv/df-bonsai/boot16.sh 5006 ourfort16 7200

    # 2. LOAD THE SAVE BY HAND. Two things that look like they would do this do not:
    #      * boot16.sh's header promises "the same battle-tested menu walk" and the file
    #        is 31 lines that stop after BOOTED — there is no walk in it.
    #      * DFHack's `load-save` script is marked UNTESTED for this version and dies on
    #        `Cannot write field viewscreen_titlest.sel_menu_line: not found`.
    #    So drive the menu, which is what bonsai_session.sh has always done:
    ./dfhack-run click-text "Continue active game"
    ./dfhack-run click-text "The Planets of Dawning"    # repeat until the save is listed
    ./dfhack-run click-text "ourfort16"
    # then poll df.global.cur_year_tick until it is non-zero

    # 3. prep it the way every episode does
    ./dfhack-run bonsai-headless-init
    ./dfhack-run lua "df.global.world.status.popups:resize(0); df.global.pause_state=true"

Verified: 164 buildings -> 1, frame 0, seven citizens. A backup of the save sits at
`/srv/df-bonsai/backups/ourfort16-pre-reset` because `load-save` warns it may corrupt a
game, and the save directory is writable.

**The order battery needs a BUILT workshop**, and a freshly loaded fort has none — every
shop it places sits at stage 0 until a dwarf walks over. Run the fort a few thousand frames
after placing one (`bonsai-run 10000 2500`) before expecting `bonsai-ordercheck` to
exercise anything. It aborts with `ABORT: no workshop; build one first` rather than
pretending.
