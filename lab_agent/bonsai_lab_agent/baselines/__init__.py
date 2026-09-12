"""Reference fort policies, tiered so improvement is measurable rather than asserted.

Each tier is importable on its own and takes the same stepped observation, so they can
be scored head to head on the same pinned save:

    v0_idle       do nothing        the score floor
    v1_developer  dig / stock / staff        development only
    v2_reactive   v1 plus threat response    development that yields to danger
    v3_survival   farms, workshops, barrels and the real brewing reaction

`v2` exists to answer a specific question — can a policy react to the game telling it
something is wrong — so it must visibly change behaviour when the threat channel
lights up, not merely carry a branch that never fires.
"""
from bonsai_lab_agent.baselines.tiers import (TIERS, v0_idle, v1_developer, v2_reactive,
                                              v3_survival)
from bonsai_lab_agent.baselines.llm_policy import llm_policy

__all__ = ["TIERS", "v0_idle", "v1_developer", "v2_reactive", "v3_survival", "llm_policy"]
