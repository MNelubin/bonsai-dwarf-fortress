"""Tests for the template and cluster library.

The library is DATA the agent chooses from, so the failure mode is not a crash but a
plausible-looking entry that describes something the game does not have. Every check here
exists because the equivalent mistake has already been made somewhere in this project:
an invented enum name, a footprint nobody verified, a cost that drifted from what the
thing actually costs.
"""

import re
from pathlib import Path

import pytest

from bonsai_lab_agent.actions.library import (BUILD_COST, BUILDING_KEYS, CLUSTER_NAMES,
                                              CLUSTERS, FURNACE_KEYS, GROUND_MODES,
                                              JOBS_OFFERED, STOCKPILE_KEYS, TEMPLATES,
                                              TEMPLATES_BY_NAME, WORKSHOP_KEYS, Cluster,
                                              LibraryError, Template, blueprint_extents,
                                              cluster, template_extent)


# ---------------------------------------------------------------- templates
def test_every_template_declares_a_real_footprint():
    """A caller asks 'does it fit' before stamping, so a missing or zero extent is a
    template that can only be applied by hoping."""
    for t in TEMPLATES:
        w, h = t.footprint
        assert w > 0 and h > 0, t.name


def test_template_names_are_unique():
    """Across shipped AND generated: a searched design that collides with a DFHack
    blueprint name would silently shadow it in the lookup."""
    from bonsai_lab_agent.actions.library import ALL_TEMPLATES
    assert len(TEMPLATES_BY_NAME) == len(ALL_TEMPLATES)
    names = [t.name for t in ALL_TEMPLATES]
    assert len(names) == len(set(names))


def test_every_template_says_what_it_makes():
    """`makes` is what the agent chooses on. A template with an empty one is a name."""
    assert [t.name for t in TEMPLATES if not t.makes.strip()] == []


def test_a_template_with_no_modes_is_refused():
    with pytest.raises(LibraryError):
        Template(name="x", path="x.csv", modes=(), footprint=(1, 1), makes="nothing")


def test_a_template_with_no_area_is_refused():
    with pytest.raises(LibraryError):
        Template(name="x", path="x.csv", modes=("dig",), footprint=(0, 5), makes="nothing")


def test_shipped_templates_point_at_csv_files():
    assert [t.name for t in TEMPLATES if not t.path.endswith(".csv")] == []


# ---------------------------------------------------------------- clusters
def test_cluster_keys_are_quickforts_own():
    """The keys are DFHack's, read out of quickfort's build.lua and place.lua. Declaring
    one it does not know would build the wrong thing, silently."""
    for c in CLUSTERS:
        for k in c.workshops:
            assert k in BUILDING_KEYS, (c.name, k)
        for k in c.stockpiles:
            assert k in STOCKPILE_KEYS, (c.name, k)


def test_no_key_names_a_building_the_verb_cannot_build():
    """`build_workshop` takes a `df.workshop_type` name. quickfort also ships `wS` (Soap
    Maker) and `wp` (Screw Press), which are `workshop_type.Custom` with custom=0/1 — real
    buildings, but NOT members of the enum, and enumerating it live is what caught them
    before they were transcribed in as though they were."""
    assert "wS" not in BUILDING_KEYS
    assert "wp" not in BUILDING_KEYS


def test_every_key_has_a_cost_and_a_capability():
    """A key the agent can choose but the library cannot price is a key that will be
    chosen blind."""
    for k in BUILDING_KEYS:
        assert k in BUILD_COST, k
        assert k in JOBS_OFFERED, k


def test_an_invented_workshop_key_is_refused():
    with pytest.raises(LibraryError):
        Cluster(name="x", size=1, workshops=("zz",), stockpiles=(),
                replenishes=("nothing",))


def test_an_invented_stockpile_key_is_refused():
    with pytest.raises(LibraryError):
        Cluster(name="x", size=1, workshops=("wc",), stockpiles=("Q",),
                replenishes=("nothing",))


def test_cluster_size_is_bounded():
    with pytest.raises(LibraryError):
        Cluster(name="x", size=9, workshops=("wc",), stockpiles=(),
                replenishes=("nothing",))


def test_cost_is_what_df_charges_not_one_per_workshop():
    """Cost is derived from DF's own build-filter table, read live with
    `getFiltersByType`. It used to be `len(workshops)`, which is right for the fifteen
    buildings whose filter is "any one building material" and wrong for the rest: Siege
    and the Ashery cost three, the forges and the Dyer's and the Millstone two."""
    for c in CLUSTERS:
        assert c.cost == sum(BUILD_COST[k] for k in c.workshops), c.name
    assert BUILD_COST["ws"] == 3 and BUILD_COST["wy"] == 3
    assert BUILD_COST["wf"] == 2 and BUILD_COST["wM"] == 2
    assert BUILD_COST["wc"] == 1
    # and a cluster with an expensive member must cost more than its member count
    metal = next(c for c in CLUSTERS if c.name == "metal" and c.size == 1)
    assert metal.cost > len(metal.workshops)


def test_capability_counts_distinct_kinds_not_copies():
    """Two Carpenter's workshops unlock no new job — they buy throughput. Counting the
    list would make size and capability the same number, and the agent would be choosing
    on one thing twice."""
    one = next(c for c in CLUSTERS if c.name == "woodworking" and c.size == 1)
    two = next(c for c in CLUSTERS if c.name == "woodworking" and c.size == 2)
    assert two.capabilities == one.capabilities
    assert two.throughput == 2 * one.throughput


def test_a_cluster_states_what_it_cannot_be_built_without():
    """A cluster the fort cannot SUPPLY is worse than one it cannot afford: it sits there
    unbuilt looking like progress. `milling` is the case — a Quern needs a manufactured
    quern item, which no fort has at embark."""
    milling = next(c for c in CLUSTERS if c.name == "milling" and c.size == 1)
    assert any("QUERN" in n for n in milling.needs)
    wood = next(c for c in CLUSTERS if c.name == "woodworking" and c.size == 1)
    assert wood.needs == ()


def test_footprint_uses_the_real_building_sizes():
    """Most workshops are 3x3, but Siege and Kennels are 5x5 and Quern and Millstone 1x1,
    from quickfort's own min/max width and height. A cluster sized as if everything were
    3x3 would be refused a site it actually fits in."""
    milling = next(c for c in CLUSTERS if c.name == "milling" and c.size == 1)
    assert milling.footprint == (4, 3)          # a 3x3 Mason's plus a 1x1 Quern
    wood = next(c for c in CLUSTERS if c.name == "woodworking" and c.size == 2)
    assert wood.footprint == (6, 3)


def test_every_cluster_says_what_it_replenishes():
    """The owner's third criterion: 'что можно восполнить, если их построить'. A cluster
    that does not answer it cannot be weighed against another."""
    assert [c.name for c in CLUSTERS if not c.replenishes] == []


def test_clusters_come_in_more_than_one_size():
    """'они могут быть разных размеров' — the point of the library is that the agent
    picks a scale, so at least one cluster has to offer a choice."""
    sizes = {}
    for c in CLUSTERS:
        sizes.setdefault(c.name, set()).add(c.size)
    assert any(len(s) > 1 for s in sizes.values()), sizes


def test_lookup_takes_the_largest_that_fits():
    assert cluster("woodworking", 1).size == 1
    assert cluster("woodworking", 2).size == 2
    assert cluster("woodworking", 3).size == 3
    assert cluster("woodworking", 4).size == 3      # nothing bigger exists yet
    assert cluster("woodworking", 0) is None
    assert cluster("no_such_cluster", 2) is None


def test_cluster_names_are_listed_once_each():
    assert len(CLUSTER_NAMES) == len(set(CLUSTER_NAMES))


# ---------------------------------------------------------------- against the game
BLUEPRINTS = Path("/srv/df-bonsai/releases/df-53.16-steam-24557528_dfhack-53.16-r1.1"
                  "/hack/data/blueprints")


@pytest.mark.skipif(not BLUEPRINTS.is_dir(),
                    reason="DFHack's blueprint library is on the lab host, not here")
def test_shipped_templates_exist_on_disk():
    missing = [t.name for t in TEMPLATES if not (BLUEPRINTS / t.path).is_file()]
    assert missing == []


@pytest.mark.skipif(not BLUEPRINTS.is_dir(),
                    reason="DFHack's blueprint library is on the lab host, not here")
def test_declared_footprints_match_the_files():
    """The extent is read off the file, so it must keep matching it.

    This used to compare against comma-fields x lines, which is the shape of the FILE and
    not of the hole it digs. Every entry passed and every entry was wrong.
    """
    for t in TEMPLATES:
        text = (BLUEPRINTS / t.path).read_text(encoding="utf-8", errors="replace")
        (w, h, levels), modes = template_extent(text)
        assert (w, h) == t.footprint, t.name
        assert levels == t.levels, t.name
        assert modes == t.modes, t.name


def test_the_parser_agrees_with_what_the_game_actually_stamped():
    """One value pinned to the map, not to the parser.

    `quickfort run -c 100,90,45 library/tombs/Mini_Saracen.csv` on the live fort put
    designations in the box 95,85..105,95 — 11x11, and at the corner `start(6;6)` predicts
    for that cursor. The file is 26 lines of up to 12 comma-fields wide, so a parser that
    counts the file agrees with nothing. Without this case, the parser and the library
    could drift together and stay consistent.
    """
    entry = TEMPLATES_BY_NAME["tombs24"]
    assert entry.footprint == (11, 11)
    assert entry.levels == 1
    assert entry.start == "6;6"


def test_quickfort_is_addressed_by_its_library_name():
    """Handing quickfort the disk-relative path gets `failed to open
    "dfhack-config/blueprints/<path>"` — a refusal that reads like a missing file."""
    assert TEMPLATES_BY_NAME["tombs24"].qf_name == "library/tombs/Mini_Saracen.csv"


def test_no_template_claims_a_text_only_section_as_ground():
    """dreamfort's notes section is 60 rows of walkthrough prose. Counting it as extent
    would tell the fort to dig a 60-tile-tall hole for a help file."""
    for t in TEMPLATES:
        assert set(t.modes) <= GROUND_MODES, t.name


@pytest.mark.skipif(not BLUEPRINTS.is_dir(),
                    reason="DFHack's blueprint library is on the lab host, not here")
def test_the_embark_cluster_matches_the_shipped_blueprint():
    """`embark` is decoded from DFHack's own file rather than invented, so the decoding
    has to keep agreeing with it: every workshop and stockpile key we claim must actually
    appear in the blueprint."""
    text = (BLUEPRINTS / "embark.csv").read_text(encoding="utf-8", errors="replace")
    cells = {c.strip() for c in re.split(r"[,\n]", text)}
    bare = {re.sub(r"\(.*", "", c) for c in cells}
    entry = next(c for c in CLUSTERS if c.name == "embark")
    assert set(entry.workshops) <= bare
    assert set(entry.stockpiles) <= bare
