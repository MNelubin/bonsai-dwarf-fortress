"""Every observation key the driver reads must be one the observer actually emits.

This is the test that was missing. `live_episode._pair_to_obs` read a `dug` key; the
observer emits `nsolid` and has never emitted `dug`, so that adapter reported zero
excavation for every episode it ever scored, and nothing failed. The two adapters have
since been collapsed into one, but the way to keep them from drifting apart again is to
check the contract itself rather than to trust that they agree.
"""
from __future__ import annotations

import re
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "bonsai_lab_agent"
OBSERVER = PKG / "dfhack" / "bonsai-observe.lua"
DRIVER = PKG / "stepped_episode.py"

# Keys the driver may read that the OBS line does not carry: supplied by the driver
# itself rather than by the observer.
NOT_FROM_OBSERVER: set[str] = set()


def observer_keys() -> set[str]:
    """The keys in the observer's OBS format string, e.g. `t=%d ncit=%d ... cids=%s`."""
    text = OBSERVER.read_text(encoding="utf-8", errors="replace")
    line = next(l for l in text.splitlines() if '"OBS t=' in l)
    return set(re.findall(r"(\w+)=%", line))


def driver_keys() -> set[str]:
    """Keys the stepped driver pulls out of a raw observation dict."""
    text = DRIVER.read_text(encoding="utf-8", errors="replace")
    direct = re.findall(r'(?:raw|d|cur_raw|before_raw|t0_raw)\.get\(\s*"(\w+)"', text)
    # `_raw_int(raw, "nstockpile")` is the other way the driver reads a key, and the first
    # version of this test missed it — so it passed while the dependency view read a key
    # the observer did not yet emit, which is exactly the bug it exists to catch.
    helper = re.findall(r'_raw_int\(\s*raw\s*,\s*"(\w+)"', text)
    return set(direct) | set(helper)


def test_observer_emits_every_key_the_driver_reads():
    missing = driver_keys() - observer_keys() - NOT_FROM_OBSERVER
    assert not missing, (
        f"the driver reads {sorted(missing)}, which the observer never emits; such a key "
        f"parses as the default forever and looks exactly like a real reading"
    )


def test_excavation_is_derived_from_the_solid_count():
    # dug_tiles has no key of its own: digging turns walls into floors, so it is the fall
    # in `nsolid` since T0. Pin this, because reading it as a key is the bug above.
    assert "nsolid" in observer_keys()
    assert "dug" not in observer_keys()


def test_no_module_defines_the_same_top_level_name_twice():
    # Python keeps the LAST definition and says nothing. A botched edit left tiers.py
    # with two `dig_request`s -- an interval formula first and the adaptive one it was
    # meant to replace second -- and the lab host ran the adaptive code for a whole
    # recalibration while the diff on the workstation read as reverted. Twelve minutes
    # of eight forts, measuring the wrong thing, with every test green.
    import ast
    for path in PKG.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        seen: dict[str, int] = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                seen[node.name] = seen.get(node.name, 0) + 1
        dupes = sorted(n for n, c in seen.items() if c > 1)
        assert not dupes, f"{path.relative_to(PKG)} defines {dupes} more than once"
