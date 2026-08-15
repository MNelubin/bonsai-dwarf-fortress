"""Tests for the action gate.

The gate is the anti-forgery boundary: everything past it is treated as legitimate, so
its failure modes matter more than most. Two properties are asserted throughout — the
gate never raises on untrusted input, and it never silently changes what was asked for
without saying so.
"""

import pytest

from bonsai_lab_agent.actions import (CATALOG, LIVE, available_actions, judge,
                                      roadmap, sanitize)
from bonsai_lab_agent.actions.schema import Arg, SchemaError, Verb


# ---------------------------------------------------------------- catalog integrity
def test_every_verb_names_an_observable():
    """A verb whose effect cannot be read back cannot be scored, and has been shipped
    before: dig designations that produced zero jobs, orders never validated into work."""
    missing = [v.name for v in CATALOG if not v.observable.strip()]
    assert missing == []


def test_planned_verbs_carry_a_tranche_and_live_ones_do_not():
    assert all(v.tranche >= 1 for v in CATALOG if v.status == "planned")
    assert all(v.tranche == 0 for v in LIVE)


def test_catalog_has_no_duplicate_verbs():
    names = [v.name for v in CATALOG]
    assert len(names) == len(set(names))


def test_required_argument_may_not_follow_an_optional_one():
    """Positional order is the wire format, so this shape would be unfillable."""
    with pytest.raises(SchemaError):
        Verb(name="x", category="c", doc="d", observable="o",
             args=(Arg("a", "int", "", required=False, default=1),
                   Arg("b", "int", "")))


# ---------------------------------------------------------------- hostile input
@pytest.mark.parametrize("junk", [None, 42, "dig", 3.5, True, object(), b"x"])
def test_garbage_yields_no_actions_and_never_raises(junk):
    clean, said = sanitize(junk)
    assert clean == []
    assert said


def test_a_bare_dict_is_one_action():
    clean, _ = sanitize({"verb": "advance"})
    assert clean == [{"verb": "advance", "args": []}]


def test_junk_among_good_actions_costs_only_itself():
    clean, said = sanitize([{"verb": "advance"}, 7, {"verb": "nope"},
                            {"verb": "build_workshop", "args": ["Still"]}])
    assert [c["verb"] for c in clean] == ["advance", "build_workshop"]
    assert len(said) == 2


# ---------------------------------------------------------------- argument binding
def test_positional_and_named_arguments_agree():
    a = judge({"verb": "add_workorder", "args": ["ConstructBed", 5]})
    b = judge({"verb": "add_workorder", "args": {"job": "ConstructBed", "amount": 5}})
    assert a.ok and b.ok and a.args == b.args == ["ConstructBed", 5, "any"]


def test_omitted_optional_argument_takes_its_default():
    d = judge({"verb": "designate_dig", "args": []})
    assert d.ok and d.args == [25]


def test_missing_required_argument_is_refused_with_the_name():
    d = judge({"verb": "add_workorder", "args": []})
    assert not d.ok and "job" in d.reason


def test_a_misspelled_argument_name_is_reported_not_ignored():
    d = judge({"verb": "add_workorder", "args": {"job": "ConstructBed", "ammount": 5}})
    assert d.ok                                   # amount falls back to its default
    assert any("ammount" in r for r in d.repairs)


# ---------------------------------------------------------------- the asymmetry
def test_out_of_range_numbers_are_clamped_and_the_repair_is_reported():
    """A scale mistake keeps the intent; the exaggeration is dropped, out loud."""
    d = judge({"verb": "designate_dig", "args": [10_000]})
    assert d.ok and d.args == [400]
    assert any("400" in r for r in d.repairs)


def test_an_unknown_enum_is_refused_because_it_cannot_be_repaired():
    d = judge({"verb": "create_zone", "args": ["throne_room"]})
    assert not d.ok


def test_a_refused_enum_lists_what_was_allowed(monkeypatch):
    """A refusal the controller cannot act on is only marginally better than silence.

    Uses a synthetic live verb: every enum in the catalog today belongs to a planned
    verb, and the planned check fires first (rightly — there is no point validating
    arguments for something that cannot dispatch), so the enum path would otherwise have
    no coverage at all.
    """
    from bonsai_lab_agent.actions import gate
    v = Verb(name="_probe", category="test", doc="d", observable="o",
             args=(Arg("kind", "enum", "which", choices=("bedroom", "pasture")),))
    monkeypatch.setitem(gate.BY_NAME, "_probe", v)

    bad = judge({"verb": "_probe", "args": ["throne_room"]})
    assert not bad.ok
    assert "bedroom" in bad.reason and "pasture" in bad.reason

    loose = judge({"verb": "_probe", "args": ["BedRoom"]})
    assert loose.ok and loose.args == ["bedroom"]
    assert loose.repairs                          # the correction is reported, not silent


def test_numbers_arrive_as_strings_and_still_work():
    d = judge({"verb": "add_workorder", "args": ["ConstructBed", "12"]})
    assert d.ok and d.args == ["ConstructBed", 12, "any"]


@pytest.mark.parametrize("truthy,expected",
                         [("yes", True), ("FALSE", False), (1, True), (0, False),
                          ("on", True), (True, True)])
def test_booleans_accept_what_a_model_actually_writes(truthy, expected):
    d = judge({"verb": "set_labor", "args": ["PLANT", truthy]})
    assert d.ok and d.args == ["PLANT", expected]


def test_an_uninterpretable_boolean_is_refused():
    d = judge({"verb": "set_labor", "args": ["PLANT", "maybe"]})
    assert not d.ok


# ---------------------------------------------------------------- planned verbs
def test_a_planned_verb_is_refused_with_its_tranche():
    d = judge({"verb": "smooth"})
    assert not d.ok and "tranche 3" in d.reason


def test_planned_verbs_stay_out_of_the_advertised_actions():
    live = {a["verb"] for a in available_actions()}
    assert "smooth" not in live
    assert "smooth" in {a["verb"] for a in available_actions(True)}


def test_the_roadmap_is_ordered_by_tranche():
    tr = [r["tranche"] for r in roadmap()]
    assert tr == sorted(tr)
    assert tr and tr[0] == min(tr)


def test_the_food_and_drink_chain_has_shipped():
    """The measured year failed on consumables: drink 12 to 0, nothing brewed. Tranche 1
    existed to fix exactly that, and it is now delivered — so these must be LIVE, and
    nothing may quietly refile them as future work."""
    live = {a["verb"] for a in available_actions()}
    assert {"build_farm_plot", "set_crop", "set_kitchen_flag"} <= live
    assert not [r for r in roadmap() if r["tranche"] == 1]


def test_standing_orders_are_live_and_guard_a_stock_level():
    """Placed as a real manager order and dispatched through the same path as a one-shot
    one, so the two cannot drift apart on which workshop or which reagent they use."""
    d = judge({"verb": "add_workorder_conditional",
               "args": ["MakeBarrel", "BARREL", 5]})
    assert d.ok
    assert d.args == ["MakeBarrel", "BARREL", 5, 10, "LessThan", "", "Daily"]
    assert "add_workorder_conditional" in {a["verb"] for a in available_actions()}


# ---------------------------------------------------------------- orderable jobs
def test_an_unorderable_job_is_refused_and_the_list_is_offered():
    """It used to fall through to a default: `add_workorder NoSuchJobType 5` queued five
    ConstructBed jobs on a live fort. A closed list makes that a refusal the controller
    can act on."""
    d = judge({"verb": "add_workorder", "args": ["BrewDrink", 5]})
    assert not d.ok
    assert "ConstructBed" in d.reason


def test_a_job_name_in_the_wrong_case_is_corrected_out_loud():
    d = judge({"verb": "add_workorder", "args": ["constructbed", 5]})
    assert d.ok and d.args == ["ConstructBed", 5, "any"]
    assert d.repairs


def test_the_conditional_verb_uses_the_same_job_list():
    assert not judge({"verb": "add_workorder_conditional",
                      "args": ["BrewDrink", "DRINK", 5]}).ok


def test_orderable_jobs_match_the_dispatcher_exactly():
    """The gate refuses what the Lua cannot queue, so the two lists drifting apart is a
    silent capability loss in one direction and a wrong-reagent job — cancelled by DF
    thousands of ticks later — in the other."""
    import re
    from pathlib import Path

    from bonsai_lab_agent.actions.catalog import ORDERABLE_JOBS

    lua = (Path(__file__).resolve().parents[1] / "bonsai_lab_agent" / "dfhack"
           / "bonsai-apply-actions.lua").read_text(encoding="utf-8")
    body = lua.split("local JOB_SPEC = {", 1)[1].split("\n}", 1)[0]
    in_lua = set(re.findall(r"^\s*(\w+)\s*=\s*\{", body, re.M))
    assert in_lua == set(ORDERABLE_JOBS), (
        f"only in Lua: {sorted(in_lua - set(ORDERABLE_JOBS))}; "
        f"only in catalog: {sorted(set(ORDERABLE_JOBS) - in_lua)}")


def test_a_standing_order_needs_a_job_to_repeat():
    assert not judge({"verb": "add_workorder_conditional", "args": []}).ok


def test_assign_noble_is_live_and_takes_best_by_default():
    """Shipped after the entity-link side effect was found: writing the assignment's
    histfig alone left getNoblePositions empty while the nobles screen read correctly."""
    d = judge({"verb": "assign_noble", "args": ["MANAGER"]})
    assert d.ok and d.args == ["MANAGER", "best"]
    assert "assign_noble" in {a["verb"] for a in available_actions()}


def test_assign_noble_refuses_an_office_that_does_not_exist():
    assert not judge({"verb": "assign_noble", "args": ["GOD_EMPEROR"]}).ok


# ---------------------------------------------------------------- discoverability
def test_advertised_actions_carry_argument_schemas():
    spec = {a["verb"]: a for a in available_actions()}
    wo = spec["add_workorder"]
    assert [x["name"] for x in wo["args"]] == ["job", "amount", "material"]
    assert wo["args"][1]["default"] == 10
    assert wo["args"][1]["range"] == [1, 200]


def test_the_schema_stays_small_enough_to_ship_every_round():
    """It rides in every controller prompt, so it is a running cost, not a one-off. The
    ceiling has moved twice — once when the order verbs gained real DF condition
    arguments and the food chain went live, once when the guide's room-and-zone set did.
    It is a budget to defend, not a formality: at 17 verbs it is 7.7 KB, and the next
    tranche should trim before it adds."""
    import json
    assert len(json.dumps(available_actions())) < 9000


def test_every_live_verb_has_a_toolbook_entry():
    """Notes drift silently: a verb ships, the doc does not mention it, and the next
    person re-derives what was already measured. The toolbook is the exhaustive record,
    so a live verb without a section in it is a gap, not a style problem."""
    from pathlib import Path

    book = (Path(__file__).resolve().parents[2] / "tools" / "df_docs"
            / "toolbook.md").read_text(encoding="utf-8")
    headings = {line[3:].strip() for line in book.splitlines() if line.startswith("## ")}
    missing = sorted(v["verb"] for v in available_actions() if v["verb"] not in headings)
    assert missing == [], f"live verbs with no toolbook section: {missing}"


def test_the_toolbook_records_a_refusal_for_every_verb_that_has_one():
    """Every verb that can refuse must say what it refuses and why — that half of the
    documentation is what stops the next silent-substitution bug being reintroduced."""
    from pathlib import Path

    book = (Path(__file__).resolve().parents[2] / "tools" / "df_docs"
            / "toolbook.md").read_text(encoding="utf-8")
    # Only verb sections. The file also documents the reachability module and the state
    # of brewing, and neither is something an agent can dispatch. `advance` takes no
    # arguments and so has nothing to refuse.
    verbs = {v["verb"] for v in available_actions()} - {"advance"}
    sections = {s.splitlines()[0]: s for s in book.split("\n## ")[1:]}
    silent = sorted(v for v in verbs if "refuse" not in sections.get(v, "").lower())
    assert silent == [], f"toolbook sections with no refusal note: {silent}"
