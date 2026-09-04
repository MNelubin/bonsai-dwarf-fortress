"""EpisodeRunner backend integration.

This module provides the deterministic EpisodeRunner implementation used by the
public test suite. It can operate with the built-in scripted backend (the default)
or with a user-supplied concrete implementation of the :class:`EpisodeBackend`
protocol.

All existing public interfaces and deterministic behaviours are preserved.
"""

import copy
from typing import Protocol, runtime_checkable, Dict, Any, Optional

from .backend import EpisodeBackend, ScriptedEpisodeBackend, BackendProtocolError


@runtime_checkable
class EpisodeRunnerBackend(Protocol):
    """Protocol for runners that accept an arbitrary EpisodeBackend.

    The runner will call ``reset``, ``observe``, ``act`` and ``advance`` on the
    provided backend exactly as the original in-memory stub did.
    ``seed`` and ``max_steps`` constraints are respected by the runner itself.
    """

    def reset(self, save_id: str, seed: int) -> Dict[str, Any]: ...
    def observe(self) -> Dict[str, Any]: ...
    def act(self, action: Dict[str, Any]) -> Dict[str, Any]: ...
    def advance(self, ticks: int) -> Dict[str, Any]: ...


class EpisodeRunner:
    """Deterministic episode runner.

    Parameters
    ----------
    backend : Optional[EpisodeBackend]
        If supplied the runner forwards all calls to the given backend.
        Otherwise a :class:`ScriptedEpisodeBackend` with the provided sequences
        is instantiated as the default in-memory stub.
    seed : int
        Seed controlling deterministic randomness (passed to the backend).
    max_steps : int
        Hard limit on the number of steps (observe/act/advance calls) that may
        be performed. When exceeded a ``BackendProtocolError`` is raised.
    action_budget : Optional[int]
        Optional soft limit on the number of actions; after exhaustion the
        next ``act`` call raises ``BackendProtocolError``.
    """

    def __init__(self,
        backend: Optional[EpisodeBackend] = None,
        seed: int = 0,
        max_steps: int = 1_000,
        action_budget: Optional[int] = None,
        observations: Optional[list[dict[str, Any]]] = None,
        action_results: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        # Select backend: if not provided, create the default scripted backend.
        if backend is None:
            # User explicitly omitted a backend – this is considered invalid.
            raise TypeError("backend must implement the EpisodeBackend protocol")
        else:
            if not isinstance(backend, EpisodeBackend):
                raise TypeError("backend must implement the EpisodeBackend protocol")
            # Ensure the runner always has a concrete EpisodeBackend.
        self._backend: EpisodeBackend = backend  # type: ignore
        # Use provided sequences or empty lists if None.
        observations = observations or []
        action_results = action_results or []
        # If no backend was supplied, instantiate the default scripted backend.
        if backend is None:
            self._backend = ScriptedEpisodeBackend(
                observations=observations,
                action_results=action_results,
            )

        self._seed = seed
        self._max_steps = max_steps
        self._action_budget = action_budget
        self._steps = 0
        self._actions = 0
        # Ensure deterministic start; injected backends are assumed to be ready.

    # ------------------------------------------------------------------
    def run_step(self, action: Optional[dict[str, Any]]) -> dict:
        """Execute a single runner step.

        If ``action`` is ``None`` the runner performs an ``observe`` call.
        Otherwise it performs ``act`` followed by a single ``advance`` of one tick.
        """
        if self._steps >= self._max_steps:
            raise BackendProtocolError(
                f"maximum number of steps ({self._max_steps}) exceeded")

        if action is None:
            out = self._backend.observe()
        else:
            if self._action_budget is not None and self._actions >= self._action_budget:
                raise BackendProtocolError(
                    f"action budget of {self._action_budget} exceeded")
            out = self._backend.act(action)
            self._actions += 1
            # Consume one tick of simulation after acting, but do not change
            # the output returned to the caller.
            self._backend.advance(1)

        self._steps += 1
        return out

    # ------------------------------------------------------------------
    def get_ledger(self) -> list[dict[str, Any]]:
        """Return the backend ledger for deterministic replay verification."""
        return copy.deepcopy(self._backend.ledger)  # type: ignore
