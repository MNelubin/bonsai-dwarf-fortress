"""Tiered reference fort policies.

Three tiers, deliberately ordered so each adds exactly one capability over the last.
That is what makes "it improves" a measurement rather than a claim: the tiers share a
save, a horizon and a decision budget, so any score difference is the capability.

    v0_idle       nothing            the floor the metric is normalised against
    v1_developer  dig / stock / staff
    v2_reactive   v1, but yields to danger

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


TIERS = {
    "v0_idle": v0_idle,
    "v1_developer": v1_developer,
    "v2_reactive": v2_reactive,
}
