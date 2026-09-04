# Time and Calendar Subsystem
## Probing the DFHack API

### Command Executed
`/srv/df-bonsai/current/dfhack-run help <command>`

### Verified Claims
- `timestream` command exists with tags fort/fps/gameplay
- `set-timeskip-duration` allows global world update modification

### Next Step
- Implement deterministic observation of game ticks via Python binding
