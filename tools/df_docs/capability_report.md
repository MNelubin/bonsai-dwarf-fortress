# Dwarf Fortress: player capability surface, survival critical path, and the agent's gaps

Grounded in the Kitfox beginner guide transcript (`D:\side_projects\bonsai_dwarf_fortress\tools\df_docs\guide_transcript.txt`) and read against the actual dispatch code at `D:\side_projects\bonsai_dwarf_fortress\lab_agent\bonsai_lab_agent\dfhack\bonsai-apply-actions.lua`, the observable vector at `...\dfhack\bonsai-observe.lua`, and the reference policies at `...\baselines\tiers.py`.

---

## 1. THE PLAYER CAPABILITY SURFACE

Nine categories. Everything a fortress-mode player does is one of these.

### A. Pre-embark run configuration â *out of scope on a pinned save*
| Verb | For |
|---|---|
| generate a world; set size, history length, civ count, site count, beast count, savagery, mineral frequency | [00:24]â[01:08] shapes the whole run before a single dwarf exists |
| pause worldgen / read Legends | [01:31] observation only |
| choose origin civilization | [02:32] parent civ; guide's heuristic is "larger population", and it highlights your civ's territory blue so you can embark near it |
| pick a site; read neighbours, aquifer, surroundings, elevation | [02:53]â[04:19] the single largest determinant of difficulty |
| set embark footprint (3x3 etc.) | [04:19] distinct from world size; performance knob |
| set difficulty / disable enemy classes | [04:40]â[05:22] also editable in-fort |

These matter to us only as *scenario* parameters. The save is pinned, so none of them belong in the action space.

### B. Perception â reading fortress state
| Verb | For |
|---|---|
| move the camera in x/y/z, zoom, hotkey-jump | [05:47]â[07:59] the substrate for every other read |
| toggle overlays: ramps (R), water depth (F) | [06:30]â[07:13] read hazards the base tileset does not show |
| re-open the mining tool to inspect droplet icons | [12:28], [13:57] the only aquifer read the guide teaches |
| read the units list (U) | [20:08] who is idle, who is doing what |
| read the kitchen menu | [10:56] what food you have and what each item can become |
| read stockpile/inventory counts (needs a record keeper) | [18:19] exact counts, not fuzzy ones |
| watch for the task check-mark | [17:32], [27:54] the confirmation that a queued job was actually *picked up* by a dwarf, not merely queued |
| read announcements | implicit throughout; the still's "no empty food storage items" [27:08] is the whole diagnosis of why brewing is stalled |

### C. Terrain â designations (marking existing rock)
| Verb | For |
|---|---|
| dig horizontally on the current z-level | [12:06] turns wall into floor; makes room volume |
| dig a stairwell: choose footprint, scroll to a terminal z, confirm | [12:28] the vertical spine of the fort |
| extend a stairwell one level at a time | [13:37] required because each damp level must be sealed before the next |
| designate individual tiles relative to prior excavation (the wall ring around a landing) | [13:57] targeted, coordinate-relative digging |
| chop wood over a dragged area | [12:52] the only source of logs |
| smooth stone | [15:46] stops aquifer flow in stone; also a happiness item [29:22] |
| set designation priority 1â7 | [14:20] at 2, miners stop losing to hauling; ordering control over queued work |
| suspend via blueprints | [13:57] the presenter dismisses it |

### D. Construction â buildings that occupy real tiles
| Verb | For |
|---|---|
| build walls / floors / stairs (Constructions menu) | [14:20]â[15:26] the aquifer seal; [29:02] repairing a mis-dug stairwell |
| choose the material explicitly, or "closest", or "last used" | [14:42]â[15:06] |
| keep building after placement | [14:42] convenience toggle for repeated placements |
| build a workshop (carpenter, stoneworker, craftsdwarf, fishery, still, kitchen, butcher, farmer's) | [16:48], [26:46], [27:08], [31:30] each is a *conversion node*: raw input in, usable good out |
| build a farm plot | [24:32] **not a workshop** â a distinct building type, must sit on soil, and must be underground for plump helmets |
| place furniture: beds, doors, tables, chairs | [17:10], [21:59], [22:21], [30:04] |

### E. Zones â rectangles painted on existing terrain that confer meaning
| Verb | For |
|---|---|
| pen/pasture | [21:39] grazers starve without one |
| bedroom (manual paint, or multi-detect on walled rooms) | [22:42]â[23:06] |
| dormitory (beds in an open room) | [23:26] the cheap shortcut |
| office | [23:46] the manager's requirement past 20 dwarves |
| gather fruit, with the step-ladder flag off | [26:25] free surface calories, no seeds and no workshop needed |
| dining hall | [30:04] |
| meeting zone | [30:50] where idle dwarves congregate |
| tavern, associated with a dining hall and a meeting zone; set visitor policy | [30:04]â[31:10] the guide keeps visitors *out* because they drink your alcohol [30:28] |

Zones are structurally the cheapest capability class in the game: a rectangle, a type, and a small options struct.

### F. Stockpiles & logistics
| Verb | For |
|---|---|
| paint a stockpile of chosen size | [08:20] |
| **choose its type** â "select all" preset or custom green/red category tree | [08:44] a stockpile with no categories accepts nothing |
| exclude bulky goods to protect capacity | [08:44]â[09:06] stone and wood cannot go in containers, so they eat a tile each |
| create a refuse pile | [09:06]â[09:28] disposal, sited away from the fort [32:14] |
| create a filtered pile placed next to its consumer | [13:17] (wood), [25:18] (seeds beside the farm) |
| **edit a live stockpile's filter after placement** | [25:40] removing seeds from the surface pile *pulls* them down to the new pile with no move order |
| set per-pile container (barrel) allowance | [25:40] zero barrels on the seed pile so seed bags stay findable |

### G. Labour & population
| Verb | For |
|---|---|
| assign the three tool-gated labours (miner, woodcutter, hunter) **per named dwarf** | [09:50] the game *refuses* blanket assignment on these three because each implies a uniform gated on a real tool |
| leave everything else alone | [10:35]â[10:56] all other labours are on for everyone by default; the skill is knowing not to touch it |
| remove one dwarf from the general labour pool (specialisation) | [29:44] stops a dedicated miner being poached onto smoothing |
| cancel a specific dwarf's current job | [20:31] frees an idle dwarf to take the task you care about |
| assign nobles: **manager**, record keeper, expedition leader | [17:55]â[18:42] the manager is what makes work orders exist at all |
| assign animals: pasture, butcher, geld | [21:18]â[21:39] |

### H. Production & job scheduling â three distinct routes
| Verb | For |
|---|---|
| queue a task directly on one workshop ("add new task") | [17:10], [31:51] **ungated** â needs no noble, enters the queue immediately |
| place a work order via the manager screen | [18:42]â[19:04] fort-wide, distributed to every workshop of that type, persists until fulfilled |
| place a work order scoped to one workshop | [19:28] manager-gated but not fort-wide |
| attach a condition to a work order | [28:14]â[28:38] "brew 25 at a time whenever drinks < 50" â converts a one-shot into a standing supply loop |

The distinction between route 1 and routes 2â3 is load-bearing and easy to miss: routes 2 and 3 require a dwarf holding the Manager position. The guide assigns it at [18:19] *specifically* to unlock automation, and warns at [19:48] that a new order lags because "your manager has to go give the orders."

### I. Fort-wide policy
| Verb | For |
|---|---|
| kitchen cook/brew flags per plant | [11:18]â[11:40] disable cooking of booze plants and plump helmets; cooking destroys seeds, brewing and raw-eating preserve them |
| standing orders (e.g. dwarves ignore outdoor refuse) | [32:14] |
| difficulty settings in-fort | [05:01] |
| retire the fortress | [32:56] survivors can reappear in a later fort |

---

## 2. THE CRITICAL PATH TO SURVIVING A YEAR

403,200 ticks = 1 DF year. 100,800 ticks per season, 33,600 per month, 1,200 per day. Seven dwarves, 12 drink and 12 food at T0 (`PINNED_T0` in `game_scorer.py`).

The guide's own framing is the three B's at [24:10]: **beds, beer, biscuits**. Only two of them kill you.

### Gate 0 â before anything moves (tick 0)
1. **Kitchen flags** [11:18]. Disable cooking on drink-capable plants and on plump helmets. This is a two-boolean action with a year-scale consequence: cooking a plump helmet destroys the seed [11:40], so an agent that queues meal jobs can eat its own farm to death in one cycle.
2. **Assign a manager** [18:19]. Nothing in the work-order system runs without it. Any dwarf will do; no office needed below 20 dwarves.
3. **Do not touch labours** [10:56]. Everything except miner/woodcutter/hunter is already on for all seven.

### Gate 1 â first weeks (~tick 0â20,000)
4. **A typed stockpile** [08:20]â[08:44], sized for the wagon load, with stone and wood excluded. The type selection is the action; an untyped pile is inert.
5. **Chop wood** [12:52] into a wood-only pile [13:17]. Logs gate barrels, barrels gate stored drink. This is the least obvious link in the chain.
6. **Dig down to soil** [12:06]â[12:28] far enough to get a plot underground. If an aquifer is in the way, this becomes the seal loop (mine the ring, wall it, repeat, then smooth once in stone) [13:57]â[16:06] â or take the guide's beginner advice and build above / dig around [16:06].
7. **Carpenter's workshop** [16:48].

### Gate 2 â must be done inside spring (before tick ~100,800)
8. **Farm plot on soil, underground** [24:32], 6x3. The guide claims a plot this size plus occasional surface gathering feeds ~50 dwarves [24:56], so throughput is not the constraint â existence is.
9. **Assign crops per season** [25:52]â[26:04]: plump helmets spring, pig tails summer, plump helmets autumn and winter. **A plot with no crop assigned for a season grows nothing.** Building the plot is half the action; this is the other half. Miss the spring window and the first harvest slips a full season.
10. **Seed stockpile beside the plot**, seeds stripped from the surface pile so the stock migrates down, barrels set to zero [25:18]â[25:40].
11. **Order barrels** [27:32]. The guide orders 20 and says you will want many more. This is the step that, missing, makes a fort *with a farm and a still* still go dry.
12. **Build the still** [27:08].

### Gate 3 â the moment barrels exist
13. **Brew drink from plant** [27:54]. Watch for the check-mark â that is the difference between "queued" and "a dwarf is doing it."
14. **Make it standing** [28:14]â[28:38]: batch 25, condition drinks < 50. This is where the guide declares the drink problem permanently solved.

### Gate 4 â free calories, any time, cheap
15. **Gather-fruit zone on the surface**, step ladders off [26:25]. No seeds, no workshop, no plot â a rectangle. Seasonal and biome-gated, so not a substitute for the farm, but the cheapest food in the game.
16. **Fishery** [26:46] if the map has water, which the guide's embark does (a creek, [04:19]).

### Gate 5 â stress, not survival, but it is scored
17. **Beds** [17:10] and either bedrooms [22:42] or a dormitory [23:26]. Dwarves sleeping rough get unhappy, not dead.
18. **Pasture** for grazers [21:39], or the livestock starve.
19. Dining hall / meeting zone / tavern [30:04]â[31:10].

**The one-line version:** logs â carpenter â barrels, and dirt â plot â seasonal crop â harvest, converge at the still. Neither branch alone produces a single unit of drink. Our measured run had neither.

---

## 3. GAP ANALYSIS AGAINST THE FIVE VERBS

Ranked by effect on surviving a year, not by interest. "Today" is judged against the real Lua dispatch, not the verb name.

| # | Capability | Guide | Agent today | What it would take |
|---|---|---|---|---|
| 1 | **Place a farm plot on soil and assign per-season crops** | [24:32], [25:52] | **No.** `build_workshop` constructs `building_type.Workshop` only; a farm plot is `building_type.FarmPlot`. And the ring placement at `u1.pos.z` is the *surface*, where plump helmets cannot grow. | New verb. Must place at a dug-out soil tile underground, not on a wagon ring, and must write the four seasonal crop slots. |
| 2 | **Make a queued job actually run** | [17:10], [19:04], [31:51] | **Doubtful.** `add_workorder` writes a bare `df.manager_order` straight into `w.manager_orders.all` with only `job_type` and amounts. It sets no id, no material, no frequency, and â critically â does not touch the order's validated/active status. In DF a work order must be validated by a dwarf holding the Manager position [18:42]. The pinned embark has no noble assigned. | Either add `assign_noble("Manager")`, or add the ungated route the guide also shows: a task queued directly on a named workshop. |
| 3 | **Give a stockpile a type** | [08:44] | **No.** `create_stockpile` calls `constructBuilding` with `abstract=true` and never writes `settings`. A stockpile with no categories enabled accepts nothing. This is very likely why stockpile creation produced buildings but no logistics. Worth verifying live before anything else on this list. | Bug fix, not a new verb: add a category argument and write the settings flags. |
| 4 | **Order barrels / empty food containers** | [27:08], [27:32] | **Partially** â `add_workorder("ConstructBarrel", 20)` is expressible *if* #2 is fixed and the enum name is right (confirm against `bonsai-dump-enums.lua`, which already dumps `job_type`). | Falls out of #2. |
| 5 | **Kitchen cook/brew flags** | [11:18] | **No.** No verb touches `ui.kitchen`. | New verb, two booleans per plant type. Cheap. |
| 6 | **Gather-fruit zone** | [26:25] | **No.** No zone verb at all. | New verb; structurally identical to `create_stockpile` (a rect plus a type plus an options flag). |
| 7 | **Standing/conditional work order** | [28:14] | **No.** `add_workorder(job, amount)` is fire-once with no condition and no frequency. | Add condition fields â *or* let the policy do it, see Â§4. |
| 8 | **Pen/pasture zone** | [21:39] | **No.** | Falls out of #6. |
| 9 | **Per-dwarf labour assignment** | [09:50], [29:44] | **No, and worse than absent.** `set_labor` writes `u.status.labors[lid] = on` across *every* citizen. For MINE/CUTWOOD/HUNT this is the exact operation the game refuses in the UI [09:50]. `v1_developer` calls `set_labor("MINE", True)` at round 0, flagging all 7 dwarves as miners against 2 picks in the fort [20:08]. Separately, v50 drives labours through work details, which may overwrite raw `status.labors` writes on the next recalculation. | Change the signature to take a unit id. Also verify the write survives; if it does not, `set_labor` is silently a no-op and the labour axis has never been exercised. |
| 10 | **Beds and bedroom/dormitory zones** | [17:10], [23:26] | **Partially** â `add_workorder("ConstructBed")` is the default fallback in the Lua, but nothing places the beds and nothing zones the room. | Furniture placement + zone verb. Stress-scored, not lethal. |
| 11 | **Build constructed walls / smooth stone** | [14:20], [15:46] | **No.** No construction primitive of any kind. | New verb. Only matters on an aquifer embark, where it is the difference between digging and not digging at all. |
| 12 | **Designation priority 1â7** | [14:20] | **No.** | Throughput. |
| 13 | **Cancel one dwarf's job** | [20:31] | **No.** | Throughput. |
| 14 | **Edit a live stockpile's filter** | [25:40] | **No.** | Logistics steering. |
| 15 | **Per-pile barrel allowance** | [25:40] | **No.** | Minor. |
| 16 | **Targeted, coordinate-relative digging** | [13:57] | **No.** `designate_dig(n)` takes a tile *count*, not a location. | The deepest schema gap â see Â§5. |
| 17 | **Tavern / meeting / dining zones, visitor policy** | [30:04]â[30:50] | **No.** | Stress and mood, long-horizon. |
| 18 | **Standing orders (outdoor refuse)** | [32:14] | **No.** | Cosmetic at one year. |

**A finding that is not a missing verb at all:** `v1_developer` in `tiers.py` never calls `add_workorder` and never calls `build_workshop("Still")`. `build_workshop` already accepts any `df.workshop_type` name, so the still â the single building the guide ties directly to survival â was *always reachable* and the reference policy simply never asked for it. Part of "nothing was ever brewed" is a policy gap, not an action-space gap. Fixing the verbs without fixing the policy will not move the number.

---

## 4. THE SHORTLIST â four verbs

I am ranking by *how much of the drink chain each one unblocks*, because the drink chain is exactly where the measured run failed. The chain is: **plants â still â empty barrel â brew job**. The agent already has the still. It has none of the other three.

### 1. `build_farm_plot(w, h, spring, summer, autumn, winter)`

The only source of brewable plants in the guide, and the only one an agent can control (surface gathering is seasonal and biome-dependent). Fused with crop assignment on purpose: the guide spends [24:32] on the plot and [25:52] on the crops, and a plot without crops is a decorative rectangle of dirt [26:04]. Splitting it into two verbs creates a state where the agent has "built a farm" and produced nothing â precisely the failure mode the current action set already has too much of.

Placement must be an argument or an internal rule, not the wagon ring: soil, underground, adjacent to the existing shaft. The dispatcher already pins the shaft head in `P.dig`, so the landing coordinates are available.

*Proves it worked:* `nbuild` +1, then `nfood` rises at the first harvest â roughly one season after planting, so by tick ~100,000â140,000. Add a `nplant_brewable` field to the observable so the policy can see the input to brewing separately from prepared food.

### 2. `queue_workshop_job(workshop_type, job_type, amount)`

This is the ungated route the guide shows twice â beds at [17:10] and cups at [31:51] â a task added at the workshop itself, requiring no noble and entering the queue immediately.

It ranks second because it is the *only* item on this list that both adds a capability and diagnoses an existing failure. If `add_workorder` has been silently dead for want of a manager, this verb produces barrels and brew jobs regardless. If `add_workorder` was working all along, this verb still gives the per-workshop targeting the guide recommends when you do not want the job spread across every shop of that type [19:28]. Either way you win, and comparing its `worders`/job output against `add_workorder`'s tells you which world you are in.

*Proves it worked:* the check-mark equivalent â a `df.job` attached to that building with a worker assigned. The current observation has no per-job state at all; add a `njobs_active` and `njobs_blocked` count. A `queue_workshop_job("Still", "BrewDrink", 10)` that queues but never attaches a worker is the exact "no empty food storage items" state at [27:08], and it should be visible as blocked, not invisible.

Pair it with `assign_noble("Manager", unit_id)` as a one-line companion if you want `add_workorder` repaired too; it is three lines of Lua and it un-breaks a verb already in the allow-list.

### 3. `create_zone(kind, w, h, opts)`

One verb, many capabilities: `gather_fruit` [26:25] is free calories on a rectangle with no prerequisites whatsoever; `pen_pasture` [21:39] stops the livestock starving; `bedroom`/`dormitory` [22:42], [23:26] and `meeting`/`dining`/`tavern` [30:04]â[31:10] all feed the stress term the scorer already measures (`strsum`, `strdang`).

It ranks third rather than first despite being the cheapest thing on the list, because gathered surface plants address *hunger* and the measured failure was *drink going to zero*. It is also seasonal â the guide only demonstrates the autumn harvest [26:25] â so it cannot be the backbone of a food supply. But it is structurally identical to `create_stockpile` (rect, type, options struct), so the implementation cost is near zero and it buys the widest surface of any single verb here.

*Proves it worked:* for `gather_fruit`, `nfood` rises in autumn with no farm plot present. For `bedroom`/`dormitory`, `strsum` diverges from the no-zone control over the second half of the year â the long-horizon comfort effect that is already an open question (task #22).

### 4. `set_kitchen_cooking(plant, cook_allowed)`

Two booleans, from [11:18]â[11:40]. It is fourth because it is prophylactic: it only bites if the agent queues meal jobs, and today it cannot. But the moment verbs 1 and 2 land, the agent *can* queue "Prepare Meal", and cooking a plump helmet destroys the seed [11:40]. A fort that cooks its seed stock has a farm that dies after one cycle and a drink supply that dies with it â a delayed, hard-to-attribute failure that shows up around tick 200,000 and looks like the farm "just stopped."

*Proves it worked:* seed count holds steady across a harvest-then-cook cycle instead of falling. Requires a seed observable, which does not exist today.

### On the conditional work order [28:14], deliberately not on this list

The guide needs "brew 25 whenever drinks < 50" because a human cannot watch the fort continuously. **Our agent gets `ndrink` in every observation and acts every round â the agent *is* the condition.** A policy that reads `obs["drink_count"] < 50` and re-issues a fixed brew order approximates the standing order exactly, at zero implementation cost in the dispatcher. Adding condition fields to `manager_order` is real work for a capability the control loop already has. Build it later, if at all; it is a convenience, not a gap.

---

## 5. WHAT THE GUIDE ASSUMES A HUMAN CAN DO

Three of these are commonly cited as blockers. Only one actually is.

### Not a blocker â reacting to announcements
This one is already solved and the project may not realise it. `bonsai-observe.lua` lines 131â146 already walks `w.status.announcements`, counts them, and keyword-filters for ambush/siege/attack/slain/**cancel**. Job-cancellation spam is the game's own error channel: "damp stone" when mining hits an aquifer [12:28], "cancels Plant seeds" when a seed bag is locked inside a hauled barrel [25:40], and the still's empty-container refusal [27:08]. The guide's diagnostic loop is *read the cancellation, fix the cause* â and that loop is mechanically available today. What is missing is that no policy branches on `warn`, and the keyword list does not include the strings that matter for the food chain. That is an afternoon of work, not a structural limit.

### Not a blocker, just work â reading the map
The guide's map reads are: droplet icons on walls [12:28], water depth overlay [07:13], ramp arrows [06:30], "have I cleared the aquifer" [16:27]. Every one of these is a tile flag or liquid field DFHack exposes directly, and the codebase already reads tiles blockwise for `nsolid` at ~30ms per sample. The agent does not need the picture; it needs the predicate. `is_aquifer(z)`, `is_soil(x,y,z)`, `nearest_soil_below_shaft()` are three small Lua functions. The guide teaches map-reading by eye because a human has no other channel; we do.

### Not a blocker, just work â judging room size, siting, and aesthetics
"Bigger rooms make happier dwarves" [20:55], "make the meeting zone at least 6x6 with no large furniture blocking dancing" [31:10], "do not give a table more than one chair" [30:04]. These are arithmetic on tile counts. They are heuristics a human eyeballs and an agent can compute more reliably.

### The real blocker â the action schema has no spatial vocabulary
Every current verb is spatially blind. `designate_dig(n_tiles)` takes a *count* and hard-codes a shaft-plus-spiral pattern. `create_stockpile(n)` and `build_workshop(type)` place on a computed ring around the first citizen at radius 4 and 8. Nothing in the allow-list accepts a coordinate, a direction, an anchor, or a reference to a previously created object.

That makes an entire class of guide content structurally inexpressible, not merely unimplemented:
- "mine the ring of wall tiles around *this* landing" [13:57]
- "put the seed pile next to *the farm plot*" [25:18]
- "wall *these four tiles*, then *those four*" [15:06]â[15:26]
- "repair *the stair that is missing*" [29:02]
- "put the refuse pile a way away from the fortress" [32:14]

The guide's implicit model is that the player names a place. Ours cannot. And note that the ring placement is not neutral â it is actively wrong for the top-ranked capability: a farm plot placed on the surface ring grows no plump helmets [24:32], so verb 1 in the shortlist cannot be implemented in the existing placement idiom at all.

Two ways out, and they are different amounts of work. The cheap one is **relational placement**: verbs take an anchor keyword (`"deepest_landing"`, `"beside:farm_plot"`, `"surface_ring"`) and the trusted dispatcher resolves it. This preserves the anti-forgery property â the agent still cannot name arbitrary memory â and covers most of the list above. The expensive one is real coordinates with validation, which reopens the trust surface. Start with anchors.

### The second real blocker â the observation cannot distinguish "built" from "working"
The guide's core feedback signal is the check-mark: at [17:32] and [27:54] it is what tells the player a dwarf has actually picked the task up. Our observation has `nbuild` (buildings exist), `worders` (order units completed), `nfood`, `ndrink` â but nothing between "I issued an intent" and "the resource number moved." A still that is built and permanently blocked on containers [27:08] is indistinguishable from a still that is brewing, until drinks appear or do not. That is a very long feedback loop for a policy that must decide something every round, and it is why a year-long run can end at drink zero with no intermediate signal that anything was wrong. Adding per-building job state (`njobs_active`, `njobs_blocked`, and the blocking reason) is the observability half of the shortlist, and without it verbs 1 and 2 will be hard to debug when they inevitably half-work."
  },
  "workflowProgress": [
    {
      "type": "workflow_phase",
      "index": 1,
      "title": "Extract"
    },
    {
      "type": "workflow_phase",
      "index": 2,
      "title": "Verify"
    },
    {
      "type": "workflow_phase",
      "index": 3,
      "title": "Map"
    },
    {
      "type": "workflow_agent",
      "index": 1,
      "label": "read:setup",
      "phaseIndex": 1,
      "phaseTitle": "Extract",
      "agentId": "acb06c4f9d668b6f8",
      "model": "claude-opus-5[1m]",
      "fallbackModel": "claude-opus-5",
      "state": "done",
      "startedAt": 1785959254901,
      "queuedAt": 1785959254823,
      "attempt": 1,
      "lastToolName": "StructuredOutput",
      "lastToolSummary": "SCOPE. Extracted only from 00:00-08:30. The stockpile paintâ¦",
      "promptPreview": "TASK CONTEXT â you are helping analyse what a Dwarf Fortress player can actually DO.

The source is a transcript of the OFFICIAL beginner guide published by Kitfox Games
(Dwarf Fortress's publisher) on 2026-08-05, 34 minutes, 8 chapters. It has been
downloaded to a local file:

    tools/df_docs/guide_transcript.txt

Format: one paragraph per ~20 seconds, each prefixed with a [MM:SS] timestamp. Reâ¦",
      "lastProgressAt": 1785959438733,
      "tokens": 47560,
      "toolCalls": 2,
      "durationMs": 183830,
      "resultPreview": "{"capabilities":[{"name":"create a new world","what":"From the main menu the player starts world generation rather than loading an existing save. This is the entry point that produces the map, the civilisations and the history everything else depends on.","category":"world-setup","timestamp":"00:24","survival_critical":false,"guide_emphasis":"walked through step by step�