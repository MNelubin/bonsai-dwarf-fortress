from dataclasses import dataclass


AUTO_PATHS = (
    "bridge/",
    "game_runner/",
    "player/",
    "skills/",
    "curricula/",
    "evaluator_public/",
    "tests/",
    "docs/",
)

PROTECTED_PATHS = (
    ".github/",
    "control_plane/",
    "db/",
    "evaluator_private/",
    "infra/",
    "security/",
)


@dataclass(frozen=True)
class PromotionEvidence:
    changed_paths: tuple[str, ...]
    unit_tests_passed: bool
    bridge_smoke_passed: bool
    short_eval_passed: bool
    full_eval_passed: bool
    median_score_delta: float
    worst_quantile_delta: float
    resource_ratio: float
    fast_forward: bool


@dataclass(frozen=True)
class PromotionDecision:
    allowed: bool
    reasons: tuple[str, ...]


def evaluate_promotion(evidence: PromotionEvidence) -> PromotionDecision:
    reasons: list[str] = []
    for path in evidence.changed_paths:
        if path.startswith(PROTECTED_PATHS):
            reasons.append(f"protected path changed: {path}")
        elif not path.startswith(AUTO_PATHS):
            reasons.append(f"path is outside auto-promotion allowlist: {path}")
    if not evidence.unit_tests_passed:
        reasons.append("unit tests failed")
    if not evidence.bridge_smoke_passed:
        reasons.append("bridge smoke test failed")
    if not evidence.short_eval_passed:
        reasons.append("short evaluation failed")
    if not evidence.full_eval_passed:
        reasons.append("full evaluation failed")
    if evidence.median_score_delta <= 0:
        reasons.append("median score did not improve")
    if evidence.worst_quantile_delta < 0:
        reasons.append("worst quantile regressed")
    if evidence.resource_ratio > 1.10:
        reasons.append("resource use regressed by more than 10%")
    if not evidence.fast_forward:
        reasons.append("promotion is not a fast-forward")
    return PromotionDecision(allowed=not reasons, reasons=tuple(reasons))

