"""Reusable skills distilled from verified action sequences."""


class Skill:
    """Base class for a reusable skill (sequence of actions)."""

    def __init__(self, name, description=""):
        self.name = name
        self.description = description
        self.actions = []

    def steps(self, observation):
        """Yield action dicts based on the current observation.

        Override in subclasses. Return None to signal termination.
        """
        raise NotImplementedError


class StartFortress(Skill):
    """Unpause the game at start of episode."""

    def __init__(self):
        super().__init__(name="start_fortress", description="Unpause a fresh game.")

    def steps(self, observation):
        if not observation.get("paused"):
            return None
        return [{"command": "unpause"}]


class AdvanceTimeStep(Skill):
    """Advance the game by a fixed tick budget per step."""

    def __init__(self, ticks=432000):
        super().__init__(name="advance_time_step", description="Advance N ticks.")
        self.ticks = ticks

    def steps(self, observation):
        return [{"command": "advance", "args": [self.ticks]}]


class CheckSurvivors(Skill):
    """Observe and check that at least one citizen lives."""

    def __init__(self, min_citizens=1):
        super().__init__(name="check_survivors", description="Ensure citizens alive.")
        self.min_citizens = min_citizens

    def steps(self, observation):
        units = observation.get("units", [])
        alive = sum(
            1 for u in units
            if not u.get("killed", False) and u.get("civ_id") is not None
        )
        return [{"command": "observe", "meta_alive": alive}]


class SurvivalGuard(Skill):
    """Terminal guard: stop the episode if survivors drop below threshold.

    Returns None when alive < min_citizens (signal skill-chain to terminate).
    Returns an observe action with alive count otherwise.
    """

    def __init__(self, min_citizens=1):
        super().__init__(
            name="survival_guard",
            description="Terminate if survivors fall below threshold.",
        )
        self.min_citizens = min_citizens

    def steps(self, observation):
        units = observation.get("units", [])
        alive = sum(
            1 for u in units
            if not u.get("killed", False) and u.get("civ_id") is not None
        )
        if alive < self.min_citizens:
            return None
        return [{"command": "observe", "meta_alive": alive}]


class GradualAdvance(Skill):
    """Incremental advance that scales tick steps by progress.

    Early game = large chunks, late game = smaller chunks.  This produces
    smoother trace output useful for CPU-policy distillation."""

    def __init__(self, max_ticks=None):
        if max_ticks is None:
            from player.baseline import TICKS_PER_DAY
            max_ticks = TICKS_PER_DAY * 30
        super().__init__(
            name="gradual_advance",
            description="Advance in variable-sized chunks based on progress.",
        )
        self.max_ticks = max_ticks

    def steps(self, observation):
        cur = observation.get("cur_tick") or 0
        if cur >= self.max_ticks:
            return None

        remaining = self.max_ticks - cur
        # Adaptive step: clamp between 1 day and 7 days.
        frac = min(1.0, remaining / self.max_ticks)
        import math
        chunk_days = max(1, min(7, int(math.ceil(frac * 7))))
        from player.baseline import TICKS_PER_DAY
        chunk = chunk_days * TICKS_PER_DAY
        return [{"command": "advance", "args": [chunk]}]


class ResourceMonitor(Skill):
    """Records observation summary without acting.

    Emits an 'observe' action that carries structured metadata for logging
    (tick progress, unit survival rate, building count).  Intended as a
    passive skill appended to chains for telemetry."""

    def __init__(self):
        super().__init__(
            name="resource_monitor",
            description="Passive observation with rich metadata.",
        )

    def steps(self, observation):
        units = observation.get("units", [])
        total = len(units)
        alive = sum(
            1 for u in units
            if not u.get("killed", False) and u.get("civ_id") is not None
        )
        return [{
            "command": "observe",
            "meta_tick_progress": (observation.get("cur_tick") or 0),
            "meta_total_units": total,
            "meta_alive": alive,
            "meta_survival_rate": (alive / total) if total else 0.0,
        }]


class EmergencyPause(Skill):
    """Reactive safety brake: pause the game when rapid citizen deaths detected.

    Tracks previous alive count internally. If more than `max_deaths` citizens
    die between observations, emit a pause action to stop further progression.
    Returns None (no-op) if conditions are safe."""

    def __init__(self, max_deaths=2):
        super().__init__(
            name="emergency_pause",
            description=f"Pause if >{max_deaths} citizens die between observations.",
        )
        self.max_deaths = max_deaths
        self._prev_alive = None

    def _count_alive(self, units):
        return sum(
            1 for u in units
            if not u.get("killed", False) and u.get("civ_id") is not None
        )

    def steps(self, observation):
        units = observation.get("units", [])
        alive = self._count_alive(units)

        if self._prev_alive is not None:
            deaths = self._prev_alive - alive
            if deaths > self.max_deaths:
                return [{"command": "pause", "meta_death_spike": deaths}]

        self._prev_alive = alive
        return None

    def reset(self):
        """Clear internal state for a fresh episode."""
        self._prev_alive = None
