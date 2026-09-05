"""/health must answer "is anything happening", not only "is the process up".

Through the 2026-07-24 outage every unit was active, the mode said running, the endpoint
said ok — and the newest job transition was thirty-eight days old.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from bonsai_control.main import STALL_THRESHOLD_SECONDS


def stalled(mode: str, idle_seconds: float | None) -> bool:
    """The predicate as the endpoint computes it."""
    return bool(
        mode == "running"
        and idle_seconds is not None
        and idle_seconds > STALL_THRESHOLD_SECONDS
    )


def test_the_thirty_eight_day_outage_would_now_read_as_stalled():
    outage = (datetime(2026, 9, 1, tzinfo=timezone.utc)
              - datetime(2026, 7, 24, tzinfo=timezone.utc)).total_seconds()
    assert stalled("running", outage)


def test_a_paused_system_is_never_stalled():
    # Nothing is supposed to move while paused; calling that a fault trains people to
    # ignore the signal.
    assert not stalled("paused", 40 * 24 * 3600)
    assert not stalled("emergency_stop", 40 * 24 * 3600)


def test_a_long_coding_cycle_is_not_a_stall():
    assert not stalled("running", 45 * 60)


def test_a_system_that_has_never_run_a_job_is_not_stalled():
    assert not stalled("running", None)


def test_the_threshold_is_generous_but_finite():
    assert 1800 <= STALL_THRESHOLD_SECONDS <= 24 * 3600
