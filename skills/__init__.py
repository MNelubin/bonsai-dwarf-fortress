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
