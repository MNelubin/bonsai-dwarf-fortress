# Calendar Mechanics
## Probing Attempt

[VERIFIED]: No DFHack commands exist for direct calendar/time manipulation in 53.15-r2.
    - Command: help time
    - Result: 653 lines of color escape sequences, no calendar-related tools

[INFERRED]: Calendar operations may require indirect state inspection via existing tools
    - Command: ls calendar
    - Result: No matches, but DFHack runtime lists 'time' tag in header (potential namespace)

## Next Steps
1. Investigate job system interactions that might reveal calendar dependencies
2. Examine tile material resolution for temporal mechanics
3. Probe unit needs patterns that correlate with in-game seasons