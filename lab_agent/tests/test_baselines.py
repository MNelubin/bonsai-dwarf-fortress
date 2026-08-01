"""Tests for the tiered baselines. The ladder only proves improvement if each tier
genuinely differs from the one below, so most of these check separation rather than
behaviour in isolation."""

import pytest

from bonsai_lab_agent.baselines import TIERS, v0_idle, v1_developer, v2_reactive


def obs(round=0, **kw):
    base = {"round": round, "rounds_total": 24, "hostiles": 0, "injured": 0,
            "danger_events": 0, "warnings": [], "under_threat": False}
    base.update(kw)
    return base


def verbs(actions):
    return [a["command"] for a in actions]


# ------------------------------------------------------------------ the floor
def test_idle_never_develops():
    """v0 is the endpoint the score is normalised against — any development here
    silently moves the floor and every other tier's score with it."""
    for r in range(24):
        assert verbs(v0_idle(obs(r))) == ["advance"]


# ------------------------------------------------------------------ v1 develops
def test_developer_opens_with_a_real_plan():
    a = verbs(v1_developer(obs(0)))
    assert "set_labor" in a and "designate_dig" in a and "create_stockpile" in a


def test_developer_keeps_digging_through_the_episode():
    digs = sum(1 for r in range(24) if "designate_dig" in verbs(v1_developer(obs(r))))
    assert digs >= 6                       # not a one-shot setup


def test_developer_builds_a_workshop():
    """Without one, no manager order can ever be worked."""
    assert any("build_workshop" in verbs(v1_developer(obs(r))) for r in range(24))


def test_developer_is_blind_to_danger():
    """v1 must NOT react — otherwise v2 adds nothing and the ladder measures noise."""
    calm = verbs(v1_developer(obs(3)))
    scared = verbs(v1_developer(obs(3, hostiles=5, under_threat=True)))
    assert calm == scared


# ------------------------------------------------------------------ v2 reacts
def test_reactive_stops_expanding_under_threat():
    v2_reactive(obs(0))                                   # reset episode state
    calm = verbs(v2_reactive(obs(3)))
    threatened = verbs(v2_reactive(obs(3, hostiles=2, under_threat=True)))
    assert "designate_dig" in calm
    assert "designate_dig" not in threatened
    assert "create_stockpile" not in threatened


@pytest.mark.parametrize("signal", [
    {"hostiles": 1}, {"injured": 2}, {"danger_events": 1},
])
def test_reactive_responds_to_every_danger_channel(signal):
    """Hostiles, injuries and the game's own announcements must all count — a policy
    that only watches one of them will sit through the others."""
    v2_reactive(obs(0))
    a = verbs(v2_reactive(obs(3, under_threat=True, **signal)))
    assert "designate_dig" not in a


def test_reactive_stays_cautious_briefly_after_the_threat_clears():
    """Resuming excavation the instant a hostile leaves the tile list walks miners
    straight back out. The hold has to outlast the sighting to be visible at all."""
    v2_reactive(obs(0))
    v2_reactive(obs(3, hostiles=1, under_threat=True))
    assert "designate_dig" not in verbs(v2_reactive(obs(4)))     # still holding
    assert "designate_dig" not in verbs(v2_reactive(obs(5)))
    resumed = any("designate_dig" in verbs(v2_reactive(obs(r))) for r in (6, 7, 8, 9))
    assert resumed                                              # but it does come back


def test_reactive_matches_the_developer_when_nothing_is_wrong():
    """The reaction must cost nothing in a calm fort, or the ladder confounds
    'reacts well' with 'develops worse'."""
    v2_reactive(obs(0))
    for r in range(1, 24):
        assert verbs(v2_reactive(obs(r))) == verbs(v1_developer(obs(r)))


def test_episode_state_does_not_leak_between_runs():
    """Round 0 resets. Without it a threatened episode would leave the next one
    cowering from a fort it never saw."""
    v2_reactive(obs(0))
    v2_reactive(obs(5, hostiles=9, under_threat=True))
    assert "designate_dig" not in verbs(v2_reactive(obs(6)))
    v2_reactive(obs(0))                                    # next episode
    assert verbs(v2_reactive(obs(3))) == verbs(v1_developer(obs(3)))


# ------------------------------------------------------------------ contract
def test_every_tier_emits_only_allow_listed_verbs():
    from bonsai_lab_agent.game_scorer import ALLOWED_VERBS, sanitize_actions
    for name, fn in TIERS.items():
        for r in range(24):
            for threat in (False, True):
                acts = fn(obs(r, under_threat=threat, hostiles=1 if threat else 0))
                assert sanitize_actions(acts) or acts == [], f"{name} r{r} dropped"
                assert all(a["command"] in ALLOWED_VERBS for a in acts), f"{name} r{r}"


def test_tier_registry_is_ordered_and_complete():
    assert list(TIERS) == ["v0_idle", "v1_developer", "v2_reactive"]
