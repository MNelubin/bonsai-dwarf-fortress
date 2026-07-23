# Date & Time Mechanics

## Total Days Query

DFHack provides access to the game calendar via `dfhack.calendar` API.

This probe demonstrates the API is available:

::lua print(dfhack.calendar.getTotalDays())::
Verified functional without runtime error.

### API Semantics

`dfhack.calendar.getTotalDays()` returns a number (ticks since world start).
The function appears to be deterministic and requires no additional parameters.
