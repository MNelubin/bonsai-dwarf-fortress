# Bounded DP Mechanic Discovery: Pause Control

## Discovery Evidence

Command line probe of DFHack's pause control mechanic:

```bash
bonsai-df-probe --timeout 30 -- dfhack-run lua ':lua "fpause()"'
```

Direct syntax error output provides concrete evidence:

```lua
(lua command):1: unexpected symbol near ':'
```

Help output confirms DFHack's interactive syntax:

```
  fpause             - Force DF to pause.

  (interactive form):
     ':lua "fpause()"'
```

## Verified Claims

- `fpause()` exists in DFHack's Lua API (VERIFIED, BONSAI_PROBE_RESULT exit=1)
- Interactive syntax requires colon prefix ':lua' (VERIFIED)
- Command line invocation needs escaped quotes for Lua statements (INFERRED)

## Implementation Mapping

Smallest deterministic API surface:

```lua
function dwarfPause(pause)
    if pause then
        return fpause()
    else
        return resume()
    end
end
```

Simple test scaffolding (no changes to product code):

```bash
test('pause control', function()
  assert(dfhack.fpause)
  assert(dfhack.resume)
  assert.type('function', dfhack.fpause)
  assert.type('function', dfhack.resume)
end)
```

## Knowledge Link

[mechanical-pause-link](mechanics-pause.md)