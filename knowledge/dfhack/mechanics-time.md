# Time Management System

## Discovery

`scripts/time` Lua module exists with implementation of time advancement and current time tracking.

`/srv/df-bonsai/current/dfhack-run help units` returns no specific unit help entries

`/srv/df-bonsai/current/dfhack-run help time` returns general DFHack help

`/srv/df-bonsai/current/dfhack-run help game_date` returns general DFHack help

## Analysis

While no existing DFHack commands expose direct time control, the presence of `scripts/time` indicates a time management subsystem that can be interacted with through Lua scripting.

This is verified through:
- `find /srv/df-bonsai/current/dfhack/scripts -type f -name 'time*'`
- Direct inspection of `scripts/time` directory
- `BONSIA_LAB_PROBE_RESULT` output from help commands

## Implementation Plan

Create a `advance <seconds>` command that calls the time script to advance game time, and an observation command to report current game time.
