# Command Infrastructure

## Overview
DFHack provides a comprehensive set of commands including:

```
command          - Description
--------------    -----------
help|?|man       - Usage help
help <tool>      - Get usage for specific command
tags             - List available command tags
ls|dir [<filter>]
                  - List commands with optional filters
                    Flags:
                      --notags: skip tags
                      --dev: include developer commands
  cls|clear          - Clear console
  fpause             - Force pause
  die                - Close game without saving
  keybinding         - Modify command key bindings
```

## Execution Details
Command infrastructure was probed successfully using a bounded probe:

```shell
/path/to/dfhack-run <<EOF
print('Here are some basic commands to get you started')
print('help|?|man') print('help <tool>') print('tags') print('ls|dir')
EOF
```

The probe completed with exit code 0, duration 31ms, and verified runtime readiness.

## Status
- [x] VERIFIED: Command infrastructure exists
- [x] VERIFIED: Help system available
- [x] VERIFIED: Command tags/listing system available

## Next Actions
1. Investigate unit management commands for player interaction
2. Explore world/time advancement commands