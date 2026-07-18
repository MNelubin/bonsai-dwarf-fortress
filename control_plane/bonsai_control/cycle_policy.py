from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CycleDecision:
    job_type: str
    reason: str


def choose_cycle(
    *,
    has_promoted_discovery: bool,
    last_job_type: str | None,
    last_job_state: str | None,
    last_job_changed: bool | None,
    promoted_coding_since_discovery: int,
) -> CycleDecision:
    if not has_promoted_discovery:
        return CycleDecision("discovery_cycle", "knowledge library has no promoted discovery yet")
    if last_job_type == "discovery_cycle" and last_job_state == "completed":
        return CycleDecision("coding_cycle", "fresh promoted knowledge is ready for implementation")
    if last_job_type in {"coding_cycle", "research_cycle"} and (
        last_job_state in {"rejected", "failed", "cancelled"} or last_job_changed is False
    ):
        return CycleDecision("discovery_cycle", "previous coding cycle produced no promotable change")
    if promoted_coding_since_discovery >= 3:
        return CycleDecision("discovery_cycle", "periodic knowledge refresh after three promoted code cycles")
    return CycleDecision("coding_cycle", "knowledge is current and coding can advance the objective")
