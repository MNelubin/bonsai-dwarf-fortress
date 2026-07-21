# Mechanics-pause advancement

## Pause & time control in DFHack

### VERIFIED 1/[0m
Command `fpause` exists to force DF to pause game simulation ([probe output](https://opencode.ai/bonsai-labs/bonsai?file=knowledge/dfhack/mechanics-pause-advancement.md&line=3)):
```
  fpause               - Force DF to pause.
```
Command sourced from dfhack-run help output.

### OPEN 2/[0m
No direct `time` command or API exposed in dfhack-run help. Likely managed via Lua `df.global.world_time` interface.

### Probe evidence
- Command `help time` not found: implies time tracking via Lua or lower-level APIs.
- `fpause` command exists but behavior unclear (requires deeper Lua investigation).

## Next executable coding task
Implement minimal stub backend in `game_runner/episode.py` exposing `reset/observe/act/advance` hooks. Write deterministic test asserting no fallback occurs when backend raises `RuntimeError`. Add `backend` parameter type-hint for future injection.

```python
# game_runner/episode.py (excerpt)
class Backend:
    def reset(self):
        raise NotImplementedError
    # observe/act/advance similar

class StubBackend(Backend):
    def reset(self):
        return {}
    # stub implementations return deterministic JSON

class EpisodeRunner:
    def __init__(self, backend: Backend):
        self.backend = backend
    # modify methods to call backend.x directly no longer using in-memory stubs

# tests/test_backend.py
def test_backend_injection(stub_backend):
    ep = EpisodeRunner(backend=stub_backend)
    with pytest.raises(RuntimeError):
        class BadBackend(Backend):
            def act(self):
                raise RuntimeError("fail")
        bad_ep = EpisodeRunner(backend=BadBackend())
        bad_ep.act()
```
# This task respects constraints: bounded to game_runner, no stubs silently fallback
# Run `pytest tests/test_backend.py && ruff check && mypy game_runner/`
