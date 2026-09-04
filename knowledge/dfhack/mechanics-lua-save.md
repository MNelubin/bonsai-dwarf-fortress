# Mechanics - Lua Save Requirement

## INFERRED
- Lua scripts (via `lua -s <file>`) require a loaded save file (failure indicates no save loaded).

## VERIFIED
- Save file loading is a prerequisite for executing Lua scripts (probe error confirms).

## OPEN
- Requires probe: Determine save-loading command sequence and test Lua execution on loaded save.

[Next task: Implement save load & Lua test]
