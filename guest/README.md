# df-bonsai guest environment

This directory layout separates downloaded candidates, activated releases, mutable state, and backups:

- `/srv/df-bonsai/staging/df-steam` — SteamCMD candidate for Dwarf Fortress app `975370`.
- `/srv/df-bonsai/staging/dfhack/<tag>` — downloaded DFHack Linux release candidates.
- `/srv/df-bonsai/releases/<version>` — immutable combined DF + DFHack releases after validation.
- `/srv/df-bonsai/current` — symlink to the active validated release.
- `/srv/df-bonsai/state` — saves and mutable configuration, kept outside release directories.
- `/srv/df-bonsai/backups` — explicit application-level backups.
- `/srv/df-bonsai/logs` — updater, smoke-test, and runtime logs.

## Commands

- `df-bonsai-status` — show SteamCMD, staging, releases, and upstream DFHack status.
- `df-steam-stage` — interactive Steam login and install/update of Dwarf Fortress into staging.
- `dfhack-stage [latest|TAG]` — download and unpack a DFHack Linux release into staging.

`df-steam-stage` deliberately requires a real terminal. Steam passwords and Steam Guard codes must be entered directly into SteamCMD and must never be placed in scripts, command-line arguments, logs, or chat messages.

Staging does not activate a release. The active validated release is selected atomically through `/srv/df-bonsai/current`.

## Active release

- Dwarf Fortress: `53.15`, Steam build `23622201`.
- DFHack: `53.15-r2`.
- Release: `/srv/df-bonsai/releases/df-53.15-steam-23622201_dfhack-53.15-r2`.
- Runtime account: `dfbot`.
- Headless settings: `PRINT_MODE:TEXT`, `SOUND:NO`.
- Validated RPC endpoint: loopback only; the smoke test used `127.0.0.1:5500`.

The smoke-test process is stopped after validation. A persistent runner and the agent-facing bridge are intentionally left for the next phase.
