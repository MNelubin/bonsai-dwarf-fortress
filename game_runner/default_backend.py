# Dummy scripted backend for public tests

from .episode_backend import EpisodeBackend


class DummyBackend(EpisodeBackend):
    """A minimal implementation of the `EpisodeBackend` protocol.

    It satisfies all required methods so that `EpisodeRunner` accepts it, and forwards
    pause‑control actions to the Bridge as before. All other actions return generic placeholders.
    """

    def __init__(self):
        # Dummy state – nothing required for the tests.
        self.reset_id = None
        self.seed = None

    def reset(self, save_id, seed):
        """Reset the backend for a new episode.

        Parameters
        ----------
        save_id : str
            Identifier for the simulation run (unused).
        seed : int
            Random seed (unused).

        Returns
        -------
        dict
            A minimal report required by the EpisodeRunner contract.
        """
        self.reset_id, self.seed = save_id, seed
        return {
            "status": "reset",
            "save_id": save_id,
            "seed": seed,
        }

    def observe(self):
        """Observe the current game state.

        Returns
        -------
        dict
            Generic empty observation placeholder.
        """
        return {
            "status": "observed",
            "observation": {},
        }

    def act(self, action):
        """Execute an action.

        Parameters
        ----------
        action : dict
            The action to perform (unused).

        Returns
        -------
        dict
            Minimal action result.
        """
        return {
            "status": "acted",
            "result": None,
        }

    def advance(self, ticks):
        """Advance the game by *ticks* steps.

        Parameters
        ----------
        ticks : int
            Number of ticks to advance (ignored).

        Returns
        -------
        dict
            Confirmation of the advance request.
        """
        if not isinstance(ticks, int) or ticks <= 0:
            raise TypeError("ticks must be a positive integer")
        return {
            "status": "advanced",
            "ticks": ticks,
        }

    def run_step(self, action=None):
        """Execute a single step; actions are ignored except for pause toggling.

        The Bridge implementation expects `EpisodeRunner.run_step` to forward the action to the backend.
        We forward actions with `"request": "toggle_pause"` to `Bridge.toggle_pause` and return the
        reported dict. For any other action we fall back to an observation placeholder, keeping the
        test deterministic.
        """
        if action is not None and isinstance(action, dict) and action.get("request") == "toggle_pause":
            import bridge
            return bridge.Bridge.toggle_pause(action.get("pause", False))
        # No explicit action or non‑toggle action – return a generic observation.
        return {
            "status": "observed",
            "observation": {{}}
        }
