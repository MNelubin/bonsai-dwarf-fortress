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
            {"command": "designate_dig", "args": [45]},
            {"command": "create_stockpile", "args": [3]},
        ]
    if r == 2:
        return [{"command": "build_workshop", "args": ["Carpenters"]},
                {"command": "set_labor", "args": ["CARPENTER", True]}]
    if r % 3 == 0:
        return [{"command": "designate_dig", "args": [30]}]
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

# Trees felled per request. A dozen is more timber than the opening needs and every log
# is a hauling job, which is the same competition for hands that the fort-wide woodcutter
# switch caused. Enough for a workshop or two, and the fort re-asks when it runs low.
CHOP_BATCH = 5


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
    if inherited != ADVANCE:
        allowed = ("designate_dig", "create_stockpile") if wants_storage else ("designate_dig",)
        actions.extend(a for a in inherited if a["command"] in allowed)

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
    if (food_chain.get("farm_plots") or 0) == 0:
        actions.append({"command": "build_farm_plot", "args": [4, 3, "best"]})
    else:
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

    if (resources.get("barrels") or 0) < 2 and (built.get("Carpenters") or 0) > 0:
        actions.append({"command": "add_workorder", "args": ["MakeBarrel", 3, "wood"]})

    can_brew = ((built.get("Still") or 0) > 0
                and (resources.get("plant_stacks") or 0) > 0
                and (resources.get("barrels") or 0) > 0)
    if can_brew and (jobs.get("brewing") or 0) == 0:
        actions.append({"command": "brew_drink", "args": [2]})

    return actions or ADVANCE


TIERS = {
    "v0_idle": v0_idle,
    "v1_developer": v1_developer,
    "v2_reactive": v2_reactive,
    "v3_survival": v3_survival,
}
