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
    return set(re.findall(r'(?:raw|d|cur_raw|before_raw|t0_raw)\.get\(\s*"(\w+)"', text))


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
