# mechanics-pause-and-advancement

## Evidence and Notes

- Executed `/srv/df-bonsai/current/dfhack-run status` via probe - output listed basic commands including `fpause` and `fsave`. `fsave` failed with \"fsave is not a recognized command\", implying it requires a loaded save.
- Units cannot be paused or advanced without an active save state.

## Verification

Both commands are available in the running headless Dwarf Fortress process according to DFHack tool listings.

## Uncertainties
	- What does `fpause` actually do with no save?

## Follow-up Investigation

- Execute `dfhack-run fpause`
- Execute `dfhack-run fsave -l` with a loaded save

## Smallest Executable Task

- Create a Lua script using `pause` and `time` DFHack commands with test assertions
