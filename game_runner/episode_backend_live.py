"""Live DFHack implementation of the EpisodeBackend protocol.

This backend is injected when the runner is configured with a non‑empty
`save_id` and a `Transport` object exposing ``run()``. It validates the
transport result shape, surfaces timeout, runtime (segfault) and invalid‑JSON
errors as structured dicts, and never silently falls back to the scripted
backend.
"""

from typing import Any, Dict, List, Optional

from bridge.contracts import EpisodeLogger
from game_runner.transport import TransportError, TransportTimeout
import json
from game_runner.transport import Transport
import copy


class BackendProtocolError(RuntimeError):
    """Raised when a backend call violates the contract returned by bridge.core."""


class LiveEpisodeBackend:
    """Backend that talks directly to a live DFHack process via the provided
    ``_dfhack_run`` transport.

    Parameters
    ----------
    transport: Transport
        Object with a ``run(lua, timeout, **kwargs)`` method returning ``dict`` or
        raising ``TransportError``/``TransportTimeout``
    logger: EpisodeLogger
        Logger instance used by the runner to record actions.
    """

    def __init__(self, transport: Transport, logger: EpisodeLogger):
        self.transport = transport
        self.logger = logger
        self.save_id: Optional[str] = None
        self.seed: Optional[int] = None
        self.ledger: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    def _validate_save_id(self, save_id: str) -> str:
        """Ensure a non‑empty pinned save identifier.

        Returns the cleaned save_id or raises ``BackendProtocolError``.
        """
        if not isinstance(save_id, str) or not save_id.strip():
            raise BackendProtocolError(
                f"save_id must be a non‑empty string, got {save_id!r}"
            )
        return save_id.strip()

    # ------------------------------------------------------------------
    def _process_transport_result(self, result: Any) -> Dict[str, Any]:
        """Normalize transport output into the contract expected by the runner.

        Returns a dict with keys ``ok`` and any contract‑specific fields.
        Raises ``BackendProtocolError`` on structured failures.
        """
        if isinstance(result, dict):
            if not isinstance(result.get("ok"), bool):
                raise BackendProtocolError(
                    f"Transport did not return 'ok' boolean: {result!r}"
                )
            return result
        raise BackendProtocolError(
            f"Transport returned unexpected type {type(result)}"
        )

    # ------------------------------------------------------------------
    def reset(self, save_id: str, seed: int) -> Dict[str, Any]:
        """Reset the episode to the pinned save.

        Delegates to ``bridge.core:reset`` via the transport.
        """
        self.save_id = self._validate_save_id(save_id)
        self.seed = int(seed)
        self.ledger = []
        lua = "require('bridge.core').reset()"
        try:
            raw = self.transport.run(lua, timeout=30)
        except TransportTimeout as exc:
            raise BackendProtocolError(f"reset timeout: {exc}") from exc
        except TransportError as exc:
            raise BackendProtocolError(f"reset transport error: {exc}") from exc
        return self._process_transport_result(raw)

    # ------------------------------------------------------------------
    def observe(self, timeout: int = 20) -> Optional[Dict[str, Any]]:
        """Obtain a fresh observation dict from bridge.core.

        If the transport fails, returns ``None``.
        """
        lua = "require('bridge.core').observe()"
        try:
            raw = self.transport.run(lua, timeout=timeout)
        except (TransportError, TransportTimeout):
            return None
        result = self._process_transport_result(raw)
        # Ensure the contract always contains the 'ok' boolean
        ok_val = result.get("ok", False)
        contract = {"ok": ok_val, **result}
        return contract

    def act(self, payload: Dict[str, Any], timeout: int = 20) -> Dict[str, Any]:
        """Dispatch a single action through the live bridge.

        Payload must contain a ``command`` key. Validation mirrors the contract,
        and any transport failure is converted to a structured error dict.
        """
        if "command" not in payload or not isinstance(payload, dict):
            raise BackendProtocolError(
                "act payload must be a dict with a 'command' field"
            )
        lua = f"require('bridge.core').act({json.dumps(payload)})"
        try:
            raw = self.transport.run(lua, timeout=timeout)
        except TransportTimeout as exc:
            raise BackendProtocolError(f"act timeout: {exc}") from exc
        except TransportError as exc:
            raise BackendProtocolError(f"act transport error: {exc}") from exc
        processed = self._process_transport_result(raw)
        # Ensure payload is echoed back when transport succeeded.
        if processed.get("ok") and "result" not in processed:
            processed["result"] = copy.deepcopy(payload)
        return processed

    # ------------------------------------------------------------------
    def advance(self, ticks: int, timeout: int = 20) -> Dict[str, Any]:
        """Advance the simulation by ``ticks``.

        ``ticks`` must be a positive integer. Errors are wrapped as contract
        ``{ok:false, message:<reason>}``.
        """
        if not isinstance(ticks, int) or ticks <= 0:
            raise BackendProtocolError(
                f"ticks must be a positive int, got {ticks!r}"
            )
        lua = f"require('bridge.core').advance({ticks})"
        try:
            raw = self.transport.run(lua, timeout=timeout)
        except (TransportError, TransportTimeout) as exc:
            return {"ok": False, "message": f"advance failed: {type(exc).__name__}"}
        return self._process_transport_result(raw)

    # ------------------------------------------------------------------
    def ledger_entry(self, step: int, observation: Dict[str, Any],
                     result: Dict[str, Any]):
        self.ledger.append({
            "step": step,
            "observation": observation,
            "result": result,
        })

    # ------------------------------------------------------------------
    def finalize(self, outcome: str, survivors: int, final_tick: int):
        self.logger.log_final(
            save_id=self.save_id,
            seed=self.seed,
            outcome=outcome,
            survivors=survivors,
            final_tick=final_tick,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "save_id": self.save_id,
            "seed": self.seed,
            "ledger": copy.deepcopy(self.ledger),
        }
