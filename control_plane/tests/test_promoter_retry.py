"""The promoter's failure classification.

A candidate that can never be pushed must be rejected, and even a transient failure
must eventually stop. Live on 2026-09-01 neither held: candidate 111d99ab sat three
commits behind GitHub main and the promoter re-attempted it every ten seconds, emitting
promotion.started / promotion.retry_scheduled indefinitely.
"""
from __future__ import annotations

from bonsai_control.promoter import (
    MAX_PROMOTION_RETRIES,
    NON_FAST_FORWARD_MARKERS,
    is_non_fast_forward,
)


def test_the_real_git_rejection_is_recognised():
    # Verbatim from the live promotion.retry_scheduled payload.
    error = (
        'RuntimeError("command failed (1): git -C /srv/bonsai-control/repo push github '
        "111d99ab44308865db70a487a7a8efe0a36a6b83:refs/heads/main\nTo "
        "https://github.com/MNelubin/bonsai-dwarf-fortress.git\n ! [rejected]          "
        "111d99ab44308865db70a487a7a8efe0a36a6b83 -> main (fetch first)\nerror: failed "
        "to push some refs to 'https://github.com/MNelubin/bonsai-dwarf-fortress.git'\n"
        "hint: Updates were rejected because the remote contains work that you do not\n"
        'have locally.")'
    )
    assert is_non_fast_forward(error)


def test_an_unrelated_failure_is_not_treated_as_permanent():
    assert not is_non_fast_forward(
        'RuntimeError("command failed (128): git push github ...\n'
        'fatal: unable to access: Could not resolve host: github.com")'
    )
    assert not is_non_fast_forward("TimeoutExpired: git push timed out after 180s")


def test_every_marker_matches_itself():
    for marker in NON_FAST_FORWARD_MARKERS:
        assert is_non_fast_forward(f"prefix {marker} suffix")


def test_retries_are_bounded():
    # The cap is the whole point: hammering a remote every ten seconds forever is how a
    # stuck candidate turns into an outage nobody notices.
    assert 1 < MAX_PROMOTION_RETRIES <= 10
