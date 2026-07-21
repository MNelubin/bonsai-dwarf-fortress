from typing import Any, Dict

class Transport:
    def run(self, lua: str, timeout: int, **kwargs) -> Dict[str, Any]:
        """A very small transport interface used by the fake backend in tests.

        In the real codebase this method would execute the provided Lua code via DFHack.
        Here we return a default contract‑shaped dict so that the public tests can import
        ``game_runner.transport.Transport`` without needing a live DF process.
        """
        return {"ok": True}

class TransportError(RuntimeError):
    pass

class TransportTimeout(TransportError):
    pass
