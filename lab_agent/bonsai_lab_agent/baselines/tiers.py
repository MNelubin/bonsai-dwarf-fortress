"""Tiered reference fort policies.

Three tiers, deliberately ordered so each adds exactly one capability over the last.
That is what makes "it improves" a measurement rather than a claim: the tiers share a
save, a horizon and a decision budget, so any score difference is the capability.

    v0_idle       nothing            the floor the metric is normalised against
    v1_developer  dig / stock / staff
    v2_reactive   v1, but yields to danger
    v3_survival   closes the measured dirt-to-beer dependency chain

Every policy takes the stepped observation and returns action intents. The evaluator
allow-lists and dispatches them; nothing here touches the game.
"""

from __future__ import annotations

ADVANCE = [{"command": "advance"}]


def v0_idle(obs: dict) -> list[dict]:
    """Do nothing. This is the no-op endpoint the score is normalised against, so it
    must stay genuinely inert — any development here silently moves the floor."""
    return ADVANCE


def v1_developer(obs: dict) -> list[dict]:
    """Dig a shaft, keep stockpiles, staff the labours. No awareness of danger.

    Deliberately plain: it should be beatable. The point of the ladder is that v2 adds
    one thing and the score moves, so v1 must not already be doing v2's job.
    """
    r = obs.get("round", 0)
    if r == 0:
        return [
            {"command": "set_labor", "args": ["MINE", True]},
            {"command": "designate_dig", "args": [dig_request(obs)]},
            {"command": "create_stockpile", "args": [3]},
        ]
    if r == 2:
        return [{"command": "build_workshop", "args": ["Carpenters"]},
                {"command": "set_labor", "args": ["CARPENTER", True]}]
    if wants_dig(obs):
        return [{"command": "designate_dig", "args": [dig_request(obs)]}]
    if r % 7 == 0:
        return [{"command": "create_stockpile", "args": [2]}]
    return ADVANCE


# How long the fort keeps its head down after the last sign of trouble. One round is
# too twitchy to see in a trace and too short to matter; a few rounds reads as a
# posture change.
THREAT_COOLDOWN_ROUNDS = 3

# Below this the fort is treated as having no usable timber. An embark arrives with a
# handful of logs in the wagon which DF will not let anyone build with, so the floor has
# to sit above that load rather than at zero.
WOOD_FLOOR = 8

# How fast a fresh embark's miners actually remove rock, measured: about 90 tiles in
# 3600 ticks when fed 12 a call every third round. Asking for more than they can reach
# before the next call does not speed them up -- it halves them. Fed 30 a call the same
# fort dug 53, fed 60 it dug 50, and the reference tiers plateaued at 93 tiles on every
# horizon because they asked a fixed 30 that a bug happened to cut to 12. The right
# request is what will be dug before the next request: rate times interval.
DIG_TILES_PER_TICK = 0.025
# ...and that fort had seven citizens. Rock removed per citizen per tick, so a fort of
# 136 is asked for what 136 can dig, not what 7 can. Measured why it matters: on the
# mature save the threat channel lights on round 2 and stays lit, so the careful tiers
# get exactly ONE dig call all episode. Asked for a seven-dwarf dozen at that call they
# dug 7 and 12 tiles where they had dug 45; asked in proportion to hands they bank
# enough work to last the hold.
DIG_TILES_PER_CITIZEN_TICK = DIG_TILES_PER_TICK / 7
DIG_EVERY_ROUNDS = 3
DIG_MIN, DIG_MAX = 12, 120


# When the standing bank of designated-but-undug rock falls under this many tiles, ask
# for more. Below it the miners are about to idle; above it, more designation only sends
# them walking (seq 527: 12 a call dug 90, 30 a call dug 46).
DIG_BACKLOG_FLOOR = 12


def dig_backlog(obs: dict) -> int | None:
    """Designated and not yet dug, or None if the observer predates the field."""
    designated = ((obs.get("dependencies") or {}).get("digging") or {}).get("designated_total")
    if designated is None:
        return None
    return max(0, int(designated) - int(obs.get("dug_tiles") or 0))


def dig_request(obs: dict) -> int:
    """Tiles to designate now.

    Learned from the player, not designed. The evolved Student (KB seq 531/532) beat this
    tier on the fresh embark by banking the whole episode's digging at round 0 -- 132
    tiles, then silence -- and let the miners work through it: 102 dug against the ~44
    this tier managed asking a dozen every third round. So: at round 0 ask for what the
    hands can dig over the WHOLE horizon; afterwards ask only when the standing backlog
    has run low, which the fort can now report (dependencies.digging.designated_total).
    This does not contradict "30 a call dug 46": that was REPEATED large asks stacking
    rock nobody could reach yet. One bank, then top-ups when it runs out, is the regime
    the player found.

    Rate times interval, and deliberately nothing cleverer. Reading the fort's own dug
    delta and asking DIG_HEADROOM times it was tried: it lifted the mature digger 110 ->
    156 but dropped the fresh fort 87 -> 67 and collapsed the threat-aware tiers on the
    mature save to 8 and 12 tiles, because a tier holding under threat digs little
    between calls, sees a small delta, asks the minimum, and spirals down. This formula
    reproduces the calibrated fresh numbers to the digit and breaks the 93-tile plateau
    at 12000 ticks (v1 dug 241). Its known cost: the rate is a seven-dwarf embark's, so a
    136-dwarf fort is asked for less than it could dig -- 85 tiles where a fixed 30 gave
    110. v1 is meant to be plain and beatable; a policy that reads its fort is v3's job.
    """
    r = int(obs.get("round", 0) or 0)
    rounds_left = max(1, int(obs.get("rounds_total", 24) or 24) - r)
    ticks_left = int(obs.get("ticks_remaining", 3600) or 3600)
    hands = max(1, int(obs.get("cohort_size", 7) or 7))
    if r == 0:
        want = round(DIG_TILES_PER_CITIZEN_TICK * hands * ticks_left)        # the bank
    else:
        chunk = max(1, ticks_left // rounds_left)
        want = round(DIG_TILES_PER_CITIZEN_TICK * hands * chunk * DIG_EVERY_ROUNDS)
    return max(DIG_MIN, min(DIG_MAX, want))


def wants_dig(obs: dict) -> bool:
    """Ask again only when the bank has run low. Without the backlog field, fall back to
    the old cadence so an older observer still gets a digging fort."""
    r = int(obs.get("round", 0) or 0)
    if r == 0:
        return True
    backlog = dig_backlog(obs)
    if backlog is None:
        return r % DIG_EVERY_ROUNDS == 0
    return backlog < DIG_BACKLOG_FLOOR


# Trees felled per request. A dozen is more timber than the opening needs and every log
# is a hauling job, which is the same competition for hands that the fort-wide woodcutter
# switch caused. Enough for a workshop or two, and the fort re-asks when it runs low.
CHOP_BATCH = 5

# Food plus drink per dwarf below which the fort is hungry and eats its livestock before
# it does anything else. The fed embark carries 24 for 7 (3.4); the hungry scenario opens at 0.
HUNGRY_BELOW = 1.0
DRINK_FLOOR = 1.0      # drink units per dwarf below which the fort starts gathering to brew
GATHER_BATCH = 20     # shrubs per gather_plants request
BARREL_FLOOR = 6      # empty barrels to keep ahead of the Still
FARM_PLOTS = 3        # plots to build before the fort stops asking; two fed nobody over a year
FISH_FLOOR = 3        # raw fish on hand before a Fishery is worth building
SLAUGHTER_EVERY = 12  # rounds between butcher marks, so the marks become meat first


def v2_reactive(obs: dict) -> list[dict]:
    """v1, but it stops expanding when the game says something is wrong.

    Reacting is not decoration. Digging pulls miners to the far end of a shaft, and
    hauling to a new stockpile walks dwarves across open ground — both are exactly the
    wrong thing to be doing while something hostile is on the map. So under threat the
    policy stops issuing outward work and holds, then resumes once the danger channel
    has been quiet for a few rounds.

    State lives on the function so a fresh episode starts clean without the caller
    having to know that.
    """
    r = obs.get("round", 0)
    if r == 0:
        v2_reactive._quiet_since = None                 # new episode, forget last one

    threatened = bool(obs.get("under_threat"))
    if threatened:
        v2_reactive._quiet_since = r
    last = getattr(v2_reactive, "_quiet_since", None)
    recently = last is not None and (r - last) < THREAT_COOLDOWN_ROUNDS

    if threatened or recently:
        # Hold: no new excavation, no new hauling targets. Keep the mining labour on so
        # anyone already underground finishes and comes home rather than idling in a
        # half-dug tunnel.
        return [{"command": "set_labor", "args": ["MINE", True]}] if threatened else ADVANCE

    return v1_developer(obs)


def v3_survival(obs: dict) -> list[dict]:
    """Dependency-aware reference policy for the first real survival vertical slice.

    This is deliberately a readable ladder rung, not a hidden oracle. It consumes the
    same trusted dependency view as a submitted controller and requests only public
    actions. The order is the one established in live 53.16 research: protect seeds and
    drink, expose soil, build/sow a farm, build the workshops, make barrels, then queue
    the raws-defined brewing reaction. Every round re-reads the fort instead of assuming
    that a previously accepted action has finished.
    """
    deps = obs.get("dependencies") or {}
    resources = deps.get("resources") or {}
    workshops = deps.get("workshops") or {}
    jobs = deps.get("jobs") or {}
    food_chain = deps.get("food_chain") or {}
    built = workshops.get("built_by_type") or {}
    pending = workshops.get("pending_by_type") or {}
    round_index = int(obs.get("round", 0))

    # Do not interpret an old observer as a fort with no supplies. The evaluator marks
    # missing dependency fields null specifically so this policy can fail safe.
    if resources.get("wood") is None or food_chain.get("farm_plots") is None:
        return ADVANCE

    # Storage the fort already has. An embark has none and needs somewhere to put food;
    # an established fort has piles everywhere and a new one only moves food around.
    stockpiles = (deps.get("logistics") or {}).get("stockpiles")

    actions = []
    if round_index == 0:
        actions.extend([
            {"command": "set_kitchen_flag", "args": ["SEEDS", False]},
            {"command": "set_kitchen_flag", "args": ["DRINK", False]},
            {"command": "set_labor", "args": ["MINE", True]},
            # Fort-wide here, unlike the woodcutter. Tried per dwarf and MEASURED it:
            # it did not save the mature fort (0.4869 against 0.4554) and it cost the
            # fresh one real work, dug 50 -> 29..39 and composite 0.5921 -> 0.5763..0.5860,
            # because on a seven-dwarf embark pinning one planter takes a pair of hands
            # out of everything else. The mature fort's losses are not caused by this
            # switch.
            {"command": "set_labor", "args": ["PLANT", True]},
            {"command": "set_labor", "args": ["BREWER", True]},
            # ONE woodcutter, not the whole fort. set_labor is fort-wide, and turning
            # CUTWOOD on for all seven with a dozen trees marked and forty logs to haul
            # starved mining completely: measured, this tier dug ZERO tiles in 28
            # fort-days while its designations kept being placed, 11-14 a round. No dug
            # soil means no farm plot ("no 4x3 plantable site" every round), no plants,
            # no brewing and no workorders -- the whole chain hung off the labour switch
            # being blunt. The catalog says as much about set_dwarf_labor: it is the
            # guide's fix for a fort where one job starved mining of hands.
            {"command": "set_dwarf_labor", "args": ["best", "CUTWOOD", True]},
            {"command": "create_stockpile", "args": [2, "food"]},
        ])

    # A rung ABOVE v2, not a policy beside it. This used to dig once, on round zero,
    # and spend the rest of the episode on a food chain it could not start -- so the
    # tier the scale calls its ceiling was beaten by the plain digger on both forts,
    # 0.5165 against 0.5870 fresh and 0.5668 against 0.6331 mature. A reference that
    # loses to a lower rung is not a reference. Development comes from v2, which
    # yields to danger; the survival chain is what v3 ADDS on top of it.
    inherited = v2_reactive(obs)
    if obs.get("under_threat"):
        # Yield with the WHOLE policy, not just the digging. Inheriting v2's restraint
        # for excavation while the survival chain kept running was worse than either
        # tier alone: on region3-lab three Forgotten Beasts arrive during the episode
        # and this tier lost 13 of 136 dwarves where idling and plain digging each lost
        # about two, scoring 0.4554 against the do-nothing floor of 0.5078. v2 already
        # says why -- work that walks dwarves across open ground is exactly what not to
        # do while something hostile is on the map -- and sowing a field is that.
        return ADVANCE
    # A food pile on a fort that already has storage is what killed this tier on the
    # mature save. Ablation, k=2 on region3-lab: with the opening create_stockpile it
    # lost 13 of 136 dwarves and scored 0.4949, BELOW the do-nothing floor of 0.5078;
    # without it, 2 lost -- the same as idling -- survival 0.818 -> 0.971, composite
    # 0.5453, and digging rose 44 -> 73 because the haulers went back to work. Dropping
    # the farm as well changed nothing (2 and 5 lost), so sowing was never the problem:
    # my own reading of the trace blamed the fields, and the measurement says storage.
    # A new pile drags hauling across the whole map, and three Forgotten Beasts arrive
    # during the episode.
    wants_storage = not stockpiles          # None (old observer) reads as "none known"
    if round_index == 0 and wants_storage:
        actions.append({"command": "create_stockpile", "args": [2, "food"]})
        # ... and keep the barrels out of it. Traced on the hungry embark over a year:
        # barrels 15 -> 3 with drink 12 -> 0, because the food pile swallowed them for
        # meat and plants, and the Still had nothing to brew INTO. Thirst reached 470k
        # with the pond frozen. A food pile without containers is the guide's own fix.
        actions.append({"command": "configure_stockpile", "args": [0, "food", False]})
    if inherited != ADVANCE:
        allowed = ("designate_dig", "create_stockpile") if wants_storage else ("designate_dig",)
        actions.extend(a for a in inherited if a["command"] in allowed)

    # A hungry fort eats its livestock first. Measured on the hungry scenario over a
    # month: every tier sat at comfort 0.44-0.68, provisioning 0.25-0.32, composite
    # 0.16-0.26 and dug nothing, because hungry dwarves do not dig and the farm's soil
    # never appears. A Butcher's plus the BUTCHER labour plus the three largest tame
    # animals marked took food 0 -> 42 in a month, comfort to 0.939, provisioning to
    # 0.500, composite to 0.380, seven of seven alive. Nothing else in the catalog came
    # close; gathering measured no better than idling (below).
    cohort = max(1, int(obs.get("cohort_size") or 1))
    # Food alone. The first version summed food and drink, so a fort with fifteen
    # barrels and nothing to eat read as fed (12/7 = 1.7) and never butchered: traced
    # on the hungry embark, hunger 364k -> 482k over a month with the livestock alive.
    food_per_dwarf = int(obs.get("food_count") or 0) / cohort
    if round_index == 0:
        v3_survival._last_slaughter = None
        v3_survival._fish_labour = False
    # The herd is eaten more than once. The first version marked three animals ONCE:
    # traced over the year, the fort had four animals standing while food went 15 -> 0
    # in winter and comfort read 0. The observer now says how many stand unmarked;
    # a hungry fort with a Butcher's marks up to three of them again, no more often
    # than every SLAUGHTER_EVERY rounds so the marks have time to become meat. On the
    # month this fires once, as before.
    livestock = int(obs.get("livestock") or 0)
    last = getattr(v3_survival, "_last_slaughter", None)
    hungry_now = food_per_dwarf < HUNGRY_BELOW
    if hungry_now and round_index == 0:
        actions.append({"command": "set_labor", "args": ["BUTCHER", True]})
    if hungry_now and (built.get("Butchers") or 0) > 0:
        if livestock > 0 and (last is None or round_index - last >= SLAUGHTER_EVERY):
            actions.append({"command": "slaughter_animal", "args": [min(3, livestock)]})
            v3_survival._last_slaughter = round_index
    elif (hungry_now and (pending.get("Butchers") or 0) == 0
            and (resources.get("wood") or 0) >= WOOD_FLOOR):
        actions.append({"command": "build_workshop", "args": ["Butchers"]})

    # The drink chain when the fort cannot dig. Traced on the hungry embark over a
    # year: meat from the butcher keeps everyone alive for months, but the Still has
    # nothing to brew, drink stays 0, and DF keeps the picks in the wagon for as long as
    # the larder holds neither food nor drink (forbid both: no pick is ever taken; forbid
    # either alone: picks in hands by round 6). No digging, so no soil, no farm, no
    # plants. Shrubs are the plants a fort gets without a dug tile: one herbalist and
    # a gathering mark, and can_brew below does the rest. This is not the gathering
    # rule that was removed (next comment): that one measured provisioning over a
    # month, when the question was drink over a year.
    drink_per_dwarf = int(obs.get("drink_count") or 0) / cohort
    if drink_per_dwarf < DRINK_FLOOR and (resources.get("plant_stacks") or 0) == 0:
        if round_index == 0:
            actions.append({"command": "set_dwarf_labor", "args": ["best", "HERBALIST", True]})
        actions.append({"command": "gather_plants", "args": [GATHER_BATCH]})

    # The fish chain. A fisherdwarf brings raw fish in from the pond all year on its own
    # (the "Fish" job ran unbidden on every fresh embark traced), and raw fish is not
    # food until a Fishery prepares it. Over the hungry year two plots and one herd
    # were not enough; this is the third source, and it needs no dug tile.
    fish_raw = int(obs.get("fish_raw") or 0)
    if fish_raw >= FISH_FLOOR:
        if (built.get("Fishery") or 0) > 0:
            if round_index == 0 or not getattr(v3_survival, "_fish_labour", False):
                actions.append({"command": "set_dwarf_labor", "args": ["best", "CLEAN_FISH", True]})
                v3_survival._fish_labour = True
            actions.append({"command": "clean_fish", "args": [min(10, fish_raw)]})
        elif (pending.get("Fishery") or 0) == 0 and (resources.get("wood") or 0) + (resources.get("boulders") or 0) > 0:
            actions.append({"command": "build_workshop", "args": ["Fishery"]})

    # Gathering when hungry was tried here and REMOVED: on the hungry scenario over a
    # month every tier's provisioning rose to 0.25-0.32 -- the idle fort included --
    # because dwarves with nothing to do gather plants on their own, and a herbalist
    # labour plus a gathering zone measured 0.268 against 0.321 without it. No benefit,
    # and a fort-wide labour switch is a known hazard (seq 509). What the scenario does
    # show is that hungry dwarves do not dig at all for at least a month.
    # The only logs on a fresh embark sit inside the wagon, and DF refuses those as
    # building material -- it cancels the job and deletes the half-built workshop. So a
    # fort that never fells a tree can never build ANY workshop, which is why this tier
    # finished zero workorders at every horizon we measured: `add_workorder` is gated on
    # a built Carpenters, and the fort was stuck reporting the same refusal for fifteen
    # rounds. `wood` counts wagon stock, so the floor has to sit above an embark load.
    if (resources.get("wood") or 0) < WOOD_FLOOR:
        actions.append({"command": "chop_trees", "args": [CHOP_BATCH]})

    # A failed early placement is expected while the soil chamber is still being dug.
    # Re-asking is idempotent once a plot exists and is evidence-driven before then.
    # One 4x3 plot fed nobody over a year: plants 0-3, seeds piling up unplanted from
    # autumn. Two plots is what the guide starts with.
    if (food_chain.get("farm_plots") or 0) < FARM_PLOTS:
        actions.append({"command": "build_farm_plot", "args": [4, 3, "best"]})
    if (food_chain.get("farm_plots") or 0) > 0:
        actions.append({"command": "set_crop", "args": ["best", "all"]})

    materials = sum(resources.get(name) or 0 for name in ("wood", "boulders", "blocks"))
    if ((built.get("Carpenters") or 0) + (pending.get("Carpenters") or 0) == 0
            and materials > 0):
        actions.extend([
            {"command": "build_workshop", "args": ["Carpenters"]},
            {"command": "set_labor", "args": ["CARPENTER", True]},
        ])
    if ((built.get("Still") or 0) + (pending.get("Still") or 0) == 0
            and materials > 0):
        actions.append({"command": "build_workshop", "args": ["Still"]})

    # Barrels are what drink lives in; two was never enough once brewing started using
    # them (the year trace above), so the floor is a brew's worth ahead.
    if ((resources.get("barrels") or 0) < BARREL_FLOOR and (built.get("Carpenters") or 0) > 0
            and (resources.get("wood") or 0) > 0):
        actions.append({"command": "add_workorder", "args": ["MakeBarrel", 3, "wood"]})

    can_brew = ((built.get("Still") or 0) > 0
                and (resources.get("plant_stacks") or 0) > 0
                and (resources.get("barrels") or 0) > 0)
    if can_brew and (jobs.get("brewing") or 0) == 0:
        actions.append({"command": "brew_drink", "args": [2]})

    return actions or ADVANCE


# ---------------------------------------------------------------- v4: settlement
#
# The catalog had 29 verbs and v3 used 16 of them; the thirteen it never touched are
# every verb about housing, furniture, zones, administration and finish. A student
# learns only what its teacher does, so in two days of forts nobody ever built a bed.
# Ten-year runs started 2026-09-15 showed why it matters: the population tripled in
# the first year on both fresh forts (7 -> 16, 7 -> 19) with nowhere to sleep or eat.
# This tier is v3 plus the settlement chain, in dependency order, each rule gated on
# what the fort reports so it re-asks only for what is still missing.
BEDROOMS_AFTER_DUG = 60     # tiles dug before the bedroom block is stamped
SMOOTH_AFTER_DUG = 150      # tiles dug before smoothing is worth a miner's time
FURNISH_EVERY = 6           # rounds between re-asking for beds, tables and rooms
SMOOTH_BATCH = 40
DINING_SEATS = 4


def v4_settlement(obs: dict) -> list[dict]:
    """v3_survival, and then the fort becomes a place to live."""
    base = [a for a in v3_survival(obs) if a.get("command") != "advance"]
    if obs.get("under_threat"):
        return base or ADVANCE                      # v3 already holds; so does this
    deps = obs.get("dependencies") or {}
    resources = deps.get("resources") or {}
    workshops = deps.get("workshops") or {}
    built = workshops.get("built_by_type") or {}
    round_index = int(obs.get("round", 0))
    citizens = max(int(obs.get("citizens") or 0), int(obs.get("cohort_alive") or 0), 1)
    dug = int(obs.get("dug_tiles") or 0)
    wood = int(resources.get("wood") or 0)
    beds = int(resources.get("beds") or 0)
    carpenters = (built.get("Carpenters") or 0) > 0
    actions = list(base)
    periodic = round_index % FURNISH_EVERY == 0
    housing = deps.get("housing") or {}
    beds_built = int(housing.get("bed") or 0)
    tables = int(housing.get("table") or 0)
    chairs = int(housing.get("chair") or 0)
    bedrooms_free = int(housing.get("bedroom_free") or 0)

    if round_index == 0:
        # A manager turns work orders into jobs; a bookkeeper keeps the stock counts the
        # policy reads honest. The herd needs a pasture or it does not eat (guide 21:18),
        # and idle dwarves need somewhere to be that is not the wagon.
        actions += [
            {"command": "assign_noble", "args": ["MANAGER", "best"]},
            {"command": "assign_noble", "args": ["BOOKKEEPER", "best"]},
        ]
    if periodic and int(housing.get("pasture") or 0) == 0:
        actions.append({"command": "create_zone", "args": ["pasture", 8, 8]})
    if periodic and int(housing.get("meeting") or 0) == 0:
        actions.append({"command": "create_zone", "args": ["meeting", 6, 6]})

    # Housing: stamp the bedroom block once the miners have a shaft to hang it on, keep
    # a bed per citizen coming from the carpenter - counting the beds already BUILT,
    # not only the loose ones, which is the difference between seven beds and a
    # hundred and forty-seven - furnish the block while loose beds exist, and hand
    # rooms out while any bedroom has no owner.
    if dug >= BEDROOMS_AFTER_DUG and carpenters:
        if periodic and int(housing.get("bedroom") or 0) == 0:
            actions.append({"command": "apply_template", "args": ["bedrooms28", "dig"]})
        want_beds = citizens - beds_built - beds
        if want_beds > 0 and wood > 0 and periodic:
            actions.append({"command": "add_workorder", "args": ["ConstructBed", min(10, want_beds), "wood"]})
        if beds > 0 and periodic:
            if int(housing.get("bedroom") or 0) == 0:
                actions.append({"command": "apply_template", "args": ["bedrooms28", "rooms"]})
            actions.append({"command": "place_furniture", "args": ["bed", min(beds, 10)]})
        # Beds outside a sleeping zone are furniture, not sleep. The bedroom block's
        # rooms stage makes bedrooms when its block was dug; when it was not (no site
        # fits the 22x23 blueprint on this embark), a dormitory over the placed beds is
        # the zone that puts everyone in a bed.
        if beds_built > 0 and int(housing.get("bedroom") or 0) == 0 and int(housing.get("dormitory") or 0) == 0 and periodic:
            actions.append({"command": "create_zone", "args": ["dormitory", 8, 8]})
        if bedrooms_free > 0:
            actions.append({"command": "assign_room", "args": ["bedroom", "any"]})

    # A dining hall: tables and chairs from the carpenter, one zone, the seats put in.
    if dug >= BEDROOMS_AFTER_DUG and carpenters and periodic and round_index >= 2 * FURNISH_EVERY:
        if wood > 0 and tables < 2:
            actions.append({"command": "add_workorder", "args": ["ConstructTable", 2 - tables, "wood"]})
        if wood > 0 and chairs < DINING_SEATS:
            actions.append({"command": "add_workorder", "args": ["ConstructThrone", DINING_SEATS - chairs, "wood"]})
        if int(housing.get("dining") or 0) == 0:
            actions.append({"command": "create_zone", "args": ["dining", 5, 5]})
        if tables < 2:
            actions.append({"command": "place_furniture", "args": ["table", 2 - tables]})
        if chairs < DINING_SEATS:
            actions.append({"command": "place_furniture", "args": ["chair", DINING_SEATS - chairs]})

    # Finish: smooth the stone once there is a fort's worth of it. Value and, on this
    # embark, the aquifer's seepage.
    if dug >= SMOOTH_AFTER_DUG and round_index % (2 * FURNISH_EVERY) == 0:
        actions.append({"command": "smooth", "args": [SMOOTH_BATCH]})

    return actions or ADVANCE


TIERS = {
    "v0_idle": v0_idle,
    "v1_developer": v1_developer,
    "v2_reactive": v2_reactive,
    "v3_survival": v3_survival,
    "v4_settlement": v4_settlement,
}
