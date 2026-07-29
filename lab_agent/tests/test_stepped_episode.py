"""Tests for the stepped episode driver (interaction model B). The DF session is
faked, so these run anywhere — no live Dwarf Fortress needed."""

import pytest

from bonsai_lab_agent import game_scorer
from bonsai_lab_agent import stepped_episode as se
from bonsai_lab_agent.session import SessionError


class FakeSession:
    """A fort that develops one building per applied action and burns food over time."""

    def __init__(self, cohort=("11", "12", "13"), die_after=None, solid=None):
        self.cohort = list(cohort)
        self.die_after = die_after
        self.tick = 2016801
        self.solid = solid          # None = observer emits no nsolid (old build)
        self.buildings = 1
        self.advances = []
        self.applied = []
        self.closed = False
        self.booted = False
        self.wildlife_suppressed = False

    def boot(self):
        self.booted = True

    def close(self):
        self.closed = True

    def suppress_wildlife(self):
        self.wildlife_suppressed = True

    def apply_actions(self, actions):
        self.applied.append(actions)
        self.buildings += len(actions)
        return f"APPLIED {len(actions)}"

    def advance(self, ticks):
        self.advances.append(ticks)
        self.tick += ticks
        return self.tick

    def observe(self):
        alive = self.cohort
        if self.die_after is not None and len(self.advances) >= self.die_after:
            alive = self.cohort[:-1]
        return {
            "t": str(self.tick), "ncit": str(len(alive)), "hsum": "100", "tsum": "80",
            "strdang": "0", "nfood": "12", "ndrink": "12",
            "nbuild": str(self.buildings), "worders": "0",
            "cids": ",".join(alive),
            **({"nsolid": str(self.solid)} if self.solid is not None else {}),
        }


class RecordingRecorder:
    def __init__(self):
        self.events = []

    def on_start(self, *a):
        self.events.append(("start", a))

    def on_round(self, *a):
        self.events.append(("round", a))

    def on_end(self, *a):
        self.events.append(("end", a))

    def close(self):
        self.events.append(("close", ()))


# ------------------------------------------------------------------ chunk_plan
@pytest.mark.parametrize("horizon,rounds", [
    (3600, 24), (12000, 24), (36000, 24), (36000, 7), (1000, 24), (100, 24), (36001, 24),
])
def test_chunk_plan_sums_exactly_to_horizon(horizon, rounds):
    """An episode that advanced the wrong total would be scored against the wrong
    calibration baseline — so the split must be exact, not approximate."""
    plan = se.chunk_plan(horizon, rounds)
    assert sum(plan) == horizon
    assert all(c > 0 for c in plan)


def test_chunk_plan_caps_rounds_for_short_horizons():
    # 300 ticks cannot support 24 rounds at a 100-tick floor
    assert len(se.chunk_plan(300, 24)) == 3
    assert se.chunk_plan(0, 24) == []


def test_chunk_plan_decision_density_is_horizon_independent():
    """Same number of decisions at every horizon, so the rungs stay comparable."""
    assert len(se.chunk_plan(3600, 24)) == len(se.chunk_plan(36000, 24)) == 24


# ------------------------------------------------------------------ the loop
def test_controller_invoked_once_per_round():
    calls = []
    s = FakeSession()
    se.run_stepped_episode(lambda obs: calls.append(obs) or [],
                           horizon_ticks=2400, rounds=6, session=s)
    assert len(calls) == 6
    assert s.advances == [400] * 6


def test_controller_sees_live_evolving_state_not_a_frozen_t0():
    """The whole point of model B: round N's observation reflects rounds 0..N-1."""
    seen = []
    s = FakeSession()
    se.run_stepped_episode(
        lambda obs: seen.append((obs["round"], obs["buildings"], obs["ticks_remaining"]))
        or [{"command": "create_stockpile", "args": [5]}],
        horizon_ticks=1200, rounds=4, session=s)
    rounds = [r for r, _, _ in seen]
    buildings = [b for _, b, _ in seen]
    remaining = [t for _, _, t in seen]
    assert rounds == [0, 1, 2, 3]
    assert buildings == [1, 2, 3, 4]          # grew as the agent's own actions landed
    assert remaining == [1200, 900, 600, 300]


def test_advance_verb_is_not_dispatched_but_round_still_advances():
    """Legacy step-loop policies return {'command':'advance'}; under model B that is a
    valid 'develop nothing this round', not an error and not a dispatched action."""
    s = FakeSession()
    se.run_stepped_episode(lambda obs: [{"command": "advance"}],
                           horizon_ticks=1200, rounds=4, session=s)
    assert s.applied == []                     # nothing dispatched
    assert s.advances == [300] * 4             # but time still passed


def test_disallowed_verbs_are_dropped_before_dispatch():
    s = FakeSession()
    se.run_stepped_episode(
        lambda obs: [{"command": "rm -rf", "args": ["/"]},
                     {"command": "set_labor", "args": ["MINE", True]}],
        horizon_ticks=600, rounds=2, session=s)
    assert [a["verb"] for batch in s.applied for a in batch] == ["set_labor", "set_labor"]


# ------------------------------------------------------------------ fail-safe
def test_crashing_controller_does_not_fail_the_episode():
    """A broken submission must score badly, not look like infrastructure failure."""
    def boom(obs):
        raise ValueError("agent exploded")

    s = FakeSession()
    t0, h = se.run_stepped_episode(boom, horizon_ticks=1200, rounds=4, session=s)
    assert s.advances == [300] * 4
    assert h.abs_tick > t0.abs_tick
    assert s.applied == []


def test_controller_returning_garbage_is_survivable():
    s = FakeSession()
    for bad in (None, "not a list", 42, [None, "x", {}]):
        se.run_stepped_episode(lambda obs, b=bad: b, horizon_ticks=300, rounds=1, session=s)
    assert len(s.advances) == 4


def test_session_error_propagates():
    """DF dying is NOT the agent's fault — it must surface, not be silently scored."""
    class Dying(FakeSession):
        def advance(self, ticks):
            raise SessionError("DF went away")

    with pytest.raises(SessionError):
        se.run_stepped_episode(lambda obs: [], horizon_ticks=600, rounds=2, session=Dying())


# ------------------------------------------------------------------ scoring surface
def test_cohort_survival_is_pinned_to_the_t0_cohort():
    s = FakeSession(cohort=("11", "12", "13"), die_after=2)
    t0, h = se.run_stepped_episode(lambda obs: [], horizon_ticks=1200, rounds=4, session=s)
    assert t0.cohort_size == 3 and t0.cohort_alive == 3
    assert h.cohort_size == 3 and h.cohort_alive == 2      # one of the starting cohort died


def test_migrants_cannot_inflate_survival():
    class Migrating(FakeSession):
        def observe(self):
            d = super().observe()
            if len(self.advances) >= 1:
                d["cids"] = d["cids"] + ",99,98"          # newcomers, not the T0 cohort
            return d

    s = Migrating(cohort=("11", "12", "13"))
    t0, h = se.run_stepped_episode(lambda obs: [], horizon_ticks=600, rounds=2, session=s)
    assert h.cohort_size == 3 and h.cohort_alive == 3      # capped at the starting seven


# ------------------------------------------------------------------ lifecycle
def test_owned_session_is_closed_even_when_the_episode_raises():
    class Dying(FakeSession):
        def advance(self, ticks):
            raise SessionError("boom")

    s = Dying()
    with pytest.raises(SessionError):
        se.run_stepped_episode(lambda obs: [], horizon_ticks=600, rounds=2, session=s)
    assert not s.closed          # caller-owned session: caller closes it

    # but a session the driver created itself must always be torn down
    import bonsai_lab_agent.stepped_episode as mod
    created = Dying()
    orig = mod.DFSession
    mod.DFSession = lambda *a, **k: created
    try:
        with pytest.raises(SessionError):
            se.run_stepped_episode(lambda obs: [], horizon_ticks=600, rounds=2)
        assert created.closed
    finally:
        mod.DFSession = orig


def test_recorder_hooks_fire_in_order_and_failures_are_swallowed():
    rec = RecordingRecorder()
    se.run_stepped_episode(lambda obs: [], horizon_ticks=900, rounds=3,
                           session=FakeSession(), recorder=rec)
    kinds = [k for k, _ in rec.events]
    assert kinds == ["start", "round", "round", "round", "end", "close"]

    class Exploding:
        def on_start(self, *a):
            raise RuntimeError("recorder is broken")
        on_round = on_end = close = on_start

    s = FakeSession()
    se.run_stepped_episode(lambda obs: [], horizon_ticks=600, rounds=2,
                           session=s, recorder=Exploding())
    assert s.advances == [300, 300]          # episode unaffected


def test_suppress_wildlife_is_forwarded():
    s = FakeSession()
    se.run_stepped_episode(lambda obs: [], horizon_ticks=300, rounds=1,
                           session=s, suppress_wildlife=True)
    assert s.wildlife_suppressed


# ------------------------------------------------------------------ development signals
def test_dug_tiles_comes_from_the_drop_in_solid_rock():
    """Digging turns walls into floors, so a falling solid-tile count IS excavation.
    Regression: the observer never emitted this and dug_tiles parsed as 0 forever, which
    left a third of the 50%-weighted development term blind however much the agent mined."""
    class Mining(FakeSession):
        def advance(self, ticks):
            self.solid -= 40                       # dwarves chew through rock
            return super().advance(ticks)

    s = Mining(solid=10_000)
    t0, h = se.run_stepped_episode(lambda o: [{"command": "designate_dig", "args": [50]}],
                                   horizon_ticks=1200, rounds=4, session=s)
    assert t0.dug_tiles == 0
    assert h.dug_tiles == 160                      # 4 rounds x 40 tiles


def test_dug_tiles_never_goes_negative():
    """Construction ADDS walls. A fort that built more than it dug must read 0, not a
    negative that would flatter the development score."""
    class Building(FakeSession):
        def advance(self, ticks):
            self.solid += 25
            return super().advance(ticks)

    _, h = se.run_stepped_episode(lambda o: [], horizon_ticks=600, rounds=2,
                                  session=Building(solid=1000))
    assert h.dug_tiles == 0


def test_recordings_without_nsolid_still_score():
    """Older observers emit no nsolid; the field must degrade to 0, not crash."""
    _, h = se.run_stepped_episode(lambda o: [], horizon_ticks=600, rounds=2,
                                  session=FakeSession(solid=None))
    assert h.dug_tiles == 0


def test_build_workshop_is_dispatched():
    """Without a workshop no manager order can be worked, so this verb is what makes the
    workorders half of the development term earnable at all."""
    s = FakeSession()
    se.run_stepped_episode(
        lambda o: [{"command": "build_workshop", "args": ["Carpenters"]},
                   {"command": "add_workorder", "args": ["ConstructBed", 5]}],
        horizon_ticks=600, rounds=2, session=s)
    verbs = [a["verb"] for batch in s.applied for a in batch]
    assert verbs == ["build_workshop", "add_workorder"] * 2


def test_controller_sees_the_new_verb():
    obs = game_scorer.controller_observation(game_scorer.PINNED_T0)
    assert "build_workshop" in obs["available_actions"]
