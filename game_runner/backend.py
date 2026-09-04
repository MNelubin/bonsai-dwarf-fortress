"""Deterministic Episode backend protocol and a scripted test backend.

This module introduces the public protocol expected from any EpisodeBackend and
provides a simple deterministic implementation used by the test suite. It does
not depend on any bridge or DFHack components.
"""

import copy
from typing import Protocol, runtime_checkable, Dict, Any


@runtime_checkable
class EpisodeBackend(Protocol):
    """Public protocol for an episode backend.

    All methods must return a JSON-serialisable dictionary (i.e. a mapping of
    JSON primitive types). The protocol is deliberately minimal to enable
    deterministic replay and testing.
    """

    def reset(self, save_id: str, seed: int) -> Dict[str, Any]:
        """Reset the backend to a fresh state.

        *save_id* is used only for logging / identification – an empty string
        is considered invalid and must raise :class:`BackendProtocolError`.
        *seed* is the integer seed governing deterministic behaviour.
        """
        ...

    def observe(self) -> Dict[str, Any]:
        """Return the current observation snapshot."""
        ...

    def act(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Process an action and return the result. *action* must be a dict; any
        other type must raise :class:`BackendProtocolError`.
        """
        ...

    def advance(self, ticks: int) -> Dict[str, Any]:
        """Advance the simulation by *ticks* steps. *ticks* must be a positive
        integer; otherwise raise :class:`BackendProtocolError`.
        """
        ...


class BackendProtocolError(Exception):
    """Raised when a backend receives invalid input or exhausts its scripted
    data.
    """
    pass


class ScriptedEpisodeBackend:
    """A deterministic, replayable backend used by the public test suite.

    The backend is fed two finite sequences during construction:

    * *observations* – a list of dictionaries that will be returned from
      :meth:`observe` method.
    * *action_results* – a list of dictionaries that will be returned from
      :meth:`act` method for each corresponding scripted action.

    The backend records every call in an ordered *ledger* and supports resetting
    to a fresh scripted episode by replaying the sequences from the beginning.
    It deep‑copies all inputs and outputs to guarantee that the caller’s data
    is never mutated.
    """

    def __init__(self,
        observations: list[dict[str, Any]],
        action_results: list[dict[str, Any]],
    ) -> None:
        self._obs_seq: list[dict[str, Any]] = copy.deepcopy(observations)
        self._act_seq: list[dict[str, Any]] = copy.deepcopy(action_results)
        self._obs_idx: int = 0
        self._act_idx: int = 0

        self.save_id: str = ""
        self.seed: int = 0
        self.ledger: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    def reset(self, save_id: str, seed: int) -> dict:
        """Reset the backend to the start of the scripted sequences.

        Raises ``BackendProtocolError`` if *save_id* is empty, *seed* is not an
        integer, or either sequence is empty.
        """
        if not save_id:
            raise BackendProtocolError("save_id must be a non‑empty string")
        if not isinstance(seed, int):
            raise BackendProtocolError("seed must be an integer")
        if not self._obs_seq and not self._act_seq:
            raise BackendProtocolError("scripted observation or action sequence empty")

        self.save_id = save_id
        self.seed = seed
        self._obs_idx = 0
        self._act_idx = 0
        self.ledger.clear()

        return {
            "status": "reset",
            "save_id": self.save_id,
            "seed": self.seed,
        }

    # ------------------------------------------------------------------
    def observe(self) -> dict:
        """Return the next scripted observation.

        Once the observation sequence is exhausted an empty dict is returned
        and :meth:`act` will subsequently raise ``BackendProtocolError``.
        """
        if self._obs_idx >= len(self._obs_seq):
            raise BackendProtocolError("no more observations (script exhausted)")
        obs = copy.deepcopy(self._obs_seq[self._obs_idx])
        self._obs_idx += 1
        self.ledger.append({"event":"observe", "output":obs})
        return obs

    # ------------------------------------------------------------------
    def act(self, action: dict) -> dict:
        """Process a scripted action.

        The *action* argument must be a dictionary; any other type raises
        ``BackendProtocolError``. When the scripted action result sequence is
        exhausted the method raises ``BackendProtocolError``.
        """
        if not isinstance(action, dict):
            raise BackendProtocolError("action must be a dict")
        if self._act_idx >= len(self._act_seq):
            raise BackendProtocolError("no more action results (script exhausted)")

        result = copy.deepcopy(self._act_seq[self._act_idx])
        self._act_idx += 1
        self.ledger.append({"event":"act", "action":action, "result":result})
        return result

    # ------------------------------------------------------------------
    def advance(self, ticks: int) -> dict:
        """Advance the simulation by *ticks* steps.

        *ticks* must be a positive integer; otherwise ``BackendProtocolError``
        is raised. The method does not consume any scripted data.
        """
        if not isinstance(ticks, int) or ticks <= 0:
            raise BackendProtocolError(
                f"ticks must be a positive integer, got {ticks!r}"
            )
        self.ledger.append({"event":"advance", "ticks":ticks})
        return {
            "status":"advanced",
            "ticks":ticks,
        }
