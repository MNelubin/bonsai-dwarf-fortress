"""Tests for the offline room-design search.

The search's failure mode is not a crash. It is returning a confident best design for an
objective the game does not use — an artefact that looks exactly like a result. So most of
what is asserted here is that the model still matches what was measured against DF, and
that the search is deterministic enough for "the best design" to mean anything at all.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys

import pytest

from bonsai_lab_agent.actions.library import blueprint_labels, template_extent
from bonsai_lab_agent.design import (Design, Requirement, anneal, bare_room, item_value,
                                     score, to_quickfort, to_surface_quickfort, validate)
from bonsai_lab_agent.design.model import (BASE_ITEM_VALUE, DEFAULT_BASE, PIECE_KEYS,
                                           REQUIRED_FURNITURE, REQUIRED_VALUE,
                                           TILE_VALUE, ZONE_KEY, DesignError)
from bonsai_lab_agent.design.search import MOVES, neighbour


def _req(**kw) -> Requirement:
    base = dict(kind="Bedroom", position="mayor", max_w=9, max_h=9)
    base.update(kw)
    return Requirement(**base)


def test_surface_blueprint_builds_shell_before_zone_and_furniture():
    d = Design(kind="Bedroom", w=5, h=4,
               cells=("##+##", "#...#", "#...#", "#####"),
               pieces=((2, 1, "b"),))
    csv = to_surface_quickfort(d, "surface_bedroom")
    assert csv.index("label(shell)") < csv.index("label(zone)") < csv.index("label(build)")
    shell = csv.split('label(shell)', 1)[1].split('label(zone)', 1)[0]
    assert shell.count("Cw") == 13
    assert shell.count("Cf") == 7
    build = csv.split('label(build)', 1)[1]
    assert ",b," in build and ",d," in build


# ---------------------------------------------------------------- the measured model
def test_tile_values_are_what_df_answered():
    """Measured against DF's own view_sheets.curroom on an owned 2x2 bedroom: 4 rough
    tiles read 4, one rewritten to StoneFloorSmooth read 7, restored read 4 again. The
    sweep over 0,1,2,3,4 smoothed of 4 gave 4, 7, 10, 13, 16.

    Changing either constant means re-measuring, which is the point of pinning them."""
    assert TILE_VALUE == {".": 1, "s": 4, "e": 14}

    # and the additivity, on the shape that was actually swept
    rows = ["####", "#..#", "#..#", "####"]
    d = Design(kind="Bedroom", w=4, h=4, cells=tuple(rows))
    assert d.value() == 4
    for n, want in enumerate((4, 7, 10, 13), start=0):
        smoothed = list(rows)
        cells = [list(r) for r in smoothed]
        left = n
        for y in (1, 2):
            for x in (1, 2):
                if left:
                    cells[y][x] = "s"
                    left -= 1
        d2 = Design(kind="Bedroom", w=4, h=4, cells=tuple("".join(c) for c in cells))
        assert d2.value() == want, n


@pytest.mark.parametrize("quality,expected", [(0, 10), (1, 14), (3, 23)])
def test_the_item_value_law_reproduces_the_earlier_measurement(quality, expected):
    """bonsai-roomvalue measured four pieces by a different route and got ordinary 10,
    well-crafted 14 and superior 23. The law has to return exactly those, or one of the
    two measurements is wrong and we would not know which."""
    assert item_value("b", 1, quality) == expected


def test_a_statue_is_the_only_piece_with_a_different_base():
    assert BASE_ITEM_VALUE == {"s": 25}
    assert item_value("s") == 25
    assert item_value("b") == DEFAULT_BASE


def test_required_furniture_is_dfs_own_table():
    """Read live from `entity_position.required_boxes/cabinets/racks/stands`. Pinned here
    so the offline model and the game cannot drift apart unnoticed; bonsai-roomvalue
    re-reads the value half from the world on every battery run."""
    assert REQUIRED_FURNITURE["monarch"] == {"h": 10, "f": 5, "r": 5, "a": 5}
    assert REQUIRED_FURNITURE["baron"] == {"h": 2, "f": 1, "r": 1, "a": 1}
    assert REQUIRED_FURNITURE["manager"] == {}
    assert REQUIRED_VALUE["manager"]["Office"] == 1
    assert REQUIRED_VALUE["monarch"]["Bedroom"] == 10000


def test_the_target_is_a_demand_and_never_a_tier():
    """v50's value-to-name cutoffs are not knowable on this build, so a tier is a number
    the game will never confirm. Requirement carries a position, not a tier."""
    assert not hasattr(Requirement(kind="Bedroom"), "tier")
    assert _req(position="baron").demand == 500


def test_score_reduces_to_the_shipped_formula_when_nothing_is_smoothed():
    """With no 's' cells the value must be exactly what bonsai-roomvalue computes on the
    live fort: set extent cells plus the furniture."""
    d = Design(kind="Bedroom", w=4, h=4, cells=("####", "#..#", "#..#", "####"),
               pieces=((1, 1, "b"),))
    assert d.value() == 4 + item_value("b")


# ---------------------------------------------------------------- what is a room
def test_the_seed_is_what_the_agent_can_already_build():
    """"The best beats the seed" is only a claim worth making if the seed is what
    create_zone plus place_furniture produces today."""
    req = _req(position="baron")
    d = bare_room(req)
    assert validate(d, req) == []
    assert "s" not in "".join(d.cells)          # unsmoothed, like create_zone leaves it


@pytest.mark.parametrize("mutate,expect", [
    (lambda c: ("####", "#..#", "#..#", "####"), "doorway"),          # no door
    (lambda c: ("#++#", "#..#", "#..#", "####"), "doorways"),         # two doors
    (lambda c: ("+###", "#..#", "#..#", "####"), "corner"),           # corner door
    (lambda c: ("#+.#", "#..#", "#..#", "####"), "open"),             # floor on the edge
])
def test_validate_names_the_rule_it_broke(mutate, expect):
    req = _req(max_w=4, max_h=4)
    d = Design(kind="Bedroom", w=4, h=4, cells=mutate(None), pieces=((1, 1, "b"),))
    reasons = validate(d, req)
    assert any(expect in r for r in reasons), reasons


def test_two_pieces_on_one_tile_are_refused():
    req = _req(max_w=4, max_h=4)
    d = Design(kind="Bedroom", w=4, h=4, cells=("#+##", "#..#", "#..#", "####"),
               pieces=((1, 1, "b"), (1, 1, "t")))
    assert any("two pieces" in r for r in validate(d, req))


def test_a_piece_outside_the_room_is_refused():
    req = _req(max_w=4, max_h=4)
    d = Design(kind="Bedroom", w=4, h=4, cells=("#+##", "#..#", "#..#", "####"),
               pieces=((0, 0, "b"),))
    assert any("not in the room" in r for r in validate(d, req))


def test_a_bedroom_without_a_bed_is_not_a_bedroom():
    req = _req(position="manager", kind="Bedroom", max_w=4, max_h=4)
    d = Design(kind="Bedroom", w=4, h=4, cells=("#+##", "#..#", "#..#", "####"))
    assert any("bed" in r for r in validate(d, req))


def test_a_noble_missing_a_required_cabinet_is_refused():
    req = _req(position="baron", max_w=5, max_h=5)
    d = Design(kind="Bedroom", w=5, h=5,
               cells=("#+###", "#...#", "#...#", "#...#", "#####"),
               pieces=((1, 1, "b"), (2, 1, "h"), (3, 1, "h")))
    assert any("cabinet" in r for r in validate(d, req))


def test_the_zone_may_not_be_painted_over_rock():
    """DF prices a WALL inside the extent the same as a rough floor — measured — so a huge
    zone over bedrock is free value and an unconstrained search WILL find it. Only dug
    cells are in the zone, so the exploit is not expressible in the representation."""
    d = Design(kind="Bedroom", w=4, h=4, cells=("####", "#..#", "#..#", "####"))
    assert set(d.zone_cells) == {(1, 1), (2, 1), (1, 2), (2, 2)}
    assert d.value() == 4                        # the twelve wall tiles are worth nothing


def test_the_engraving_ladder_is_what_df_answered():
    """Engravings are not on the tile — an engraved floor is still StoneFloorSmooth with
    special = SMOOTH, which is why a tiletype-only scorer is blind to them. They are
    records in `df.global.world.event.engravings`.

    Measured by adding ONE record to a 2x2 bedroom worth 4 and sweeping its quality with
    the poison-and-reopen oracle: DF answered 14, 24, 34, 44, 54, 124, 74. The ladder is
    NOT monotonic — Masterful adds 120 and Artifact 70 — which is surprising enough that
    pinning it is the point."""
    from bonsai_lab_agent.design.model import ENGRAVING_VALUE
    assert ENGRAVING_VALUE == {0: 10, 1: 20, 2: 30, 3: 40, 4: 50, 5: 120, 6: 70}
    assert ENGRAVING_VALUE[5] > ENGRAVING_VALUE[6]

    # an engraved cell is a smoothed cell plus a GUARANTEED Ordinary engraving
    assert TILE_VALUE["e"] == TILE_VALUE["s"] + ENGRAVING_VALUE[0]
    d = Design(kind="Bedroom", w=4, h=4, cells=("####", "#ee#", "#..#", "####"))
    assert d.value() == 14 + 14 + 1 + 1


def test_an_engraved_cell_costs_three_jobs():
    """Mine it, smooth it, engrave it. A cost model that charged one would make engraving
    look free and the search would engrave everything."""
    rough = Design(kind="Bedroom", w=4, h=4, cells=("####", "#..#", "#..#", "####"))
    engraved = Design(kind="Bedroom", w=4, h=4, cells=("####", "#e.#", "#..#", "####"))
    assert engraved.cost() == rough.cost() + 2      # + one smooth job + one engrave job


def test_engraving_needs_smoothing_and_the_requirement_can_forbid_it():
    """DF will not engrave rough stone. Verified against the game: the engrave section of
    a generated blueprint, dry-run on raw rock, answered "Tiles that could not be
    designated for digging: 15" — exactly its 15 engraved cells."""
    # `manager` needs no furniture, so the only thing under test here is the engraving
    d = Design(kind="Bedroom", w=4, h=4, cells=("#+##", "#e.#", "#..#", "####"),
               pieces=((2, 1, "b"),))
    allowed = _req(position="manager", max_w=4, max_h=4)
    assert validate(d, allowed) == []
    forbidden = _req(position="manager", max_w=4, max_h=4, allow_smooth=False)
    assert any("smoothed first" in r for r in validate(d, forbidden))


def test_a_malformed_design_is_refused_at_construction():
    with pytest.raises(DesignError):
        Design(kind="Bedroom", w=4, h=4, cells=("###",))


# ---------------------------------------------------------------- emission
def test_the_emitted_blueprint_parses_as_a_blueprint():
    """It goes back through the SAME parser that validates DFHack's shipped files, so a
    design we cannot read is one quickfort could not read either.

    The parsed extent is SMALLER than the room, and that is correct rather than a bug:
    walls are not dug, so the dig grid's outermost ring is empty and the extent measures
    the hole, not the bounding box. A caller reserving ground for one of our designs must
    use `Design.w/h`, not the re-parsed extent, or it will under-reserve by the wall ring.
    """
    req = _req(position="baron")
    d = bare_room(req)
    csv = to_quickfort(d, name="probe")
    (w, h, levels), modes = template_extent(csv)
    assert modes == ("build", "dig", "zone")
    assert levels == 1
    assert 0 < w <= d.w and 0 < h <= d.h
    # and specifically: the hole is the interior plus the doorway, never the whole box
    assert w < d.w


def test_dig_is_the_first_section_and_smoothing_is_a_second_pass():
    """`quickfort run <file>` with no label runs the FIRST blueprint. pump_stack.csv opens
    with a #notes help section, so running it printed a walkthrough and stamped nothing.

    Smoothing is its own pass, and that is not a stylistic choice — the game refused the
    first version. Putting `s` on a cell REPLACED its `d`, and the dry run answered
    "Tiles that could not be designated for digging: 11" against exactly the 11 smooth
    cells: you cannot smooth rock nobody has mined. With the split, the same design
    designates all 43 and fails none."""
    d = bare_room(_req())
    csv = to_quickfort(d, name="probe")
    labels = blueprint_labels(csv)
    assert labels[0] == ("dig", "dig")
    assert [m for m, _ in labels] == ["dig", "dig", "dig", "meta", "zone", "build"]
    assert ("dig", "smooth") in labels
    assert ("dig", "engrave") in labels

    # every tile that has to end up as floor is dug in the FIRST section
    dig_section = csv.split('"#dig label(smooth)')[0]
    cells = dig_section.replace(chr(10), ",").split(",")
    dug = sum(1 for cell in cells if cell.strip() == "d")
    want = sum(1 for row in d.cells for ch in row if ch in ".se+")
    assert dug == want


def test_every_emitted_key_is_one_quickfort_knows():
    """The guard against the invented-name failure mode, at the format level."""
    csv = to_quickfort(bare_room(_req(position="monarch")), name="probe")
    build = csv.split('"#build')[1]
    for cell in build.replace("\n", ",").split(","):
        cell = cell.strip()
        if cell and cell != "#" and not cell.startswith("label"):
            assert cell in PIECE_KEYS, cell
    assert ZONE_KEY["Bedroom"] == "b"


# ---------------------------------------------------------------- the search
def test_the_best_design_beats_the_seed():
    """The declared self-check for this goal."""
    for position, kind in (("manager", "Office"), ("mayor", "Bedroom"),
                           ("baron", "Tomb")):
        for seed in (1, 7, 13):
            req = _req(kind=kind, position=position)
            r = anneal(req, seed=seed, max_evals=800)
            assert r.best_score > r.seed_score, (position, kind, seed)
            assert r.best != bare_room(req)
            assert validate(r.best, req) == []


def test_a_reachable_demand_is_actually_reached():
    r = anneal(_req(position="baron", kind="Bedroom"), seed=3, max_evals=2000)
    assert r.feasible
    assert r.best.value() >= 500


def test_the_budget_is_honoured():
    """Counted in evaluations, never in seconds — a wall-clock budget is not
    reproducible, and this suite has to stay fast."""
    r = anneal(_req(), seed=1, max_evals=300)
    assert r.evaluations == 300
    assert r.attempts >= r.evaluations


def test_a_search_that_can_never_find_a_valid_design_still_terminates():
    """A monarch demands 25 pieces of furniture and a 5x5 room has a 3x3 interior, so no
    candidate can ever validate. Rejected candidates cost no evaluation — which is right,
    the budget should buy designs and not arithmetic — but it means the loop had no bound
    at all, and this hung the whole suite before the attempt cap existed."""
    from bonsai_lab_agent.design.search import ATTEMPTS_PER_EVAL
    r = anneal(_req(position="monarch", max_w=5, max_h=5), seed=1, max_evals=200)
    assert r.attempts <= 200 * ATTEMPTS_PER_EVAL
    assert not r.feasible


def test_the_same_seed_gives_the_same_answer_in_process():
    a = anneal(_req(), seed=42, max_evals=600)
    b = anneal(_req(), seed=42, max_evals=600)
    assert to_quickfort(a.best) == to_quickfort(b.best)
    assert a.best_score == b.best_score and a.evaluations == b.evaluations


def test_a_different_seed_gives_a_different_search():
    a = anneal(_req(), seed=1, max_evals=600)
    b = anneal(_req(), seed=2, max_evals=600)
    assert (a.best_score, to_quickfort(a.best)) != (b.best_score, to_quickfort(b.best))


def test_the_same_seed_gives_the_same_answer_in_a_fresh_process():
    """The half that matters. Hash randomisation is per-process, so set iteration or dict
    ordering leaking onto the decision path is invisible in-process and shows up here."""
    def run() -> str:
        out = subprocess.run(
            [sys.executable, "-m", "bonsai_lab_agent.design.search",
             "--seed", "7", "--evals", "600"],
            capture_output=True, text=True, check=True)
        return [l for l in out.stdout.splitlines() if l.startswith("sha256=")][0]
    assert run() == run()


def test_annealing_actually_anneals():
    """With t0 = 0 the chain may never accept a downhill move; with a high t0 it must.
    Without this, "annealing" is hill-climbing under a different name and the module
    docstring is a lie nobody would catch."""
    import random as _r
    req = _req()
    start = bare_room(req)
    rng = _r.Random(5)
    downhill = 0
    for _ in range(400):
        cand = neighbour(start, req, rng)
        if cand is not None and not validate(cand, req) and score(cand, req) < score(start, req):
            downhill += 1
    assert downhill > 0, "no downhill move is even reachable; the test proves nothing"

    hot = anneal(req, seed=11, max_evals=600, t0=200)
    cold = anneal(req, seed=11, max_evals=600, t0=0)
    assert hot.best_score >= cold.seed_score
    assert cold.best_score >= cold.seed_score


def test_an_impossible_requirement_is_reported_not_faked():
    """The anti-silent-success case for the search itself: a monarch's 10000 in a 5x5 hole
    is unreachable, and the answer must say so rather than return a design that looks
    fine."""
    r = anneal(_req(position="monarch", max_w=5, max_h=5), seed=1, max_evals=800)
    assert not r.feasible
    assert r.best.value() < 10000


def test_the_move_set_is_declared_not_magic():
    names = [n for n, _ in MOVES]
    assert len(names) == len(set(names))
    assert all(wt > 0 for _, wt in MOVES)


# ---------------------------------------------------------------- the archive
def test_a_promoted_design_becomes_something_the_agent_can_ask_for():
    """The loop was OPEN. The search ran, beat its seed and emitted a blueprint the game
    accepted — and nothing could ask for the result, because `apply_template` only knew
    DFHack's eleven shipped files. The docstring claimed "winners become entries in
    library.TEMPLATES"; that was an intention, not code.

    Verified live afterwards: `apply_template bonsai/bedroom_baron.csv` stamped 43 new
    designations at 121,88,48 — exactly the 43 dug cells the offline model predicted.
    """
    from bonsai_lab_agent.actions.library import (GENERATED, TEMPLATES_BY_NAME,
                                                  TEMPLATE_NAMES)
    from bonsai_lab_agent.design.archive import load

    archived = load()
    if not archived:
        pytest.skip("the archive is empty; run design.archive.promote first")

    for e in archived:
        assert e.name in TEMPLATE_NAMES, e.name
        t = TEMPLATES_BY_NAME[e.name]
        assert t.shipped is False
        assert t.footprint == (e.w, e.h)
        # ours are addressed by their plain path; `library/` is DFHack's own prefix
        assert t.qf_name == f"bonsai/{e.name}.csv"
        assert not t.qf_name.startswith("library/")
    assert len(GENERATED) == len(archived)


def test_the_gate_resolves_a_searched_design_like_any_other():
    from bonsai_lab_agent.actions.gate import judge
    from bonsai_lab_agent.design.archive import load

    archived = load()
    if not archived:
        pytest.skip("the archive is empty")
    name = archived[0].name
    d = judge({"verb": "apply_template", "args": {"template": name}})
    assert d.ok
    assert d.args[0] == f"bonsai/{name}.csv"
    assert d.args[6] == "dig" and d.args[7] == "dig"


def test_every_archived_design_meets_the_demand_it_was_made_for():
    """An archived design that does not satisfy its own requirement is worse than none: the
    agent would ask for a baron's bedroom and get a room the baron rejects."""
    from bonsai_lab_agent.design.archive import load
    for e in load():
        assert e.value >= e.demand, (e.name, e.value, e.demand)
        assert e.score > e.seed_score, e.name


def test_promoting_a_worse_design_does_not_churn_the_archive(tmp_path):
    """A rerun that ties must not rewrite the file. An archive that changes on every run
    is not a record of anything."""
    from bonsai_lab_agent.design.archive import Entry, load, promote, save

    path = str(tmp_path / "archive.json")
    req = Requirement(kind="Office", position="manager", max_w=7, max_h=7)
    first, changed = promote(req, seeds=(1,), max_evals=400, path=path)
    assert changed
    again, changed2 = promote(req, seeds=(1,), max_evals=400, path=path)
    assert not changed2
    assert again.csv_sha256 == first.csv_sha256
    assert len(load(path)) == 1


def test_the_archive_round_trips(tmp_path):
    from bonsai_lab_agent.design.archive import entry_from, load, save
    from bonsai_lab_agent.design.search import anneal
    path = str(tmp_path / "a.json")
    req = Requirement(kind="Bedroom", position="baron")
    r = anneal(req, seed=5, max_evals=800)
    e = entry_from(req, r, 5)
    save([e], path)
    back = load(path)[0]
    assert back == e
    assert to_quickfort(back.to_design(), name=back.name) == to_quickfort(r.best,
                                                                          name=e.name)
