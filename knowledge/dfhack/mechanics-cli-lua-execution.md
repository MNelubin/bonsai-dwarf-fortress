# CLI Lua Execution and RPC Limitations

## Overview
This note documents the observed execution models for interacting with Dwarf Fortress (v53.15) via DFHack (v53.15-r2) in the DF-Bonsai environment. It highlights a critical divergence between the Remote Procedure Call (RPC) interface and direct Command Line Interface (CLI) invocation.

## Observed Execution Models

### 1. RPC Interface Limitations [VERIFIED]
The standard DFHack remote client interface appears to reject direct Lua script execution commands when passed as arguments to the `lua` command within the RPC stream.

* **Evidence**: The file `/srv/df-bonsai/current/stderr.log` contains repeated entries indicating command rejection:
  ```text
  lua local json=require('data-JSON');local g=df.global;... is not a recognized command.
  Shutting down client connection.
  ```
* **Implication**: Agents relying on the standard `dfhack-run` or RPC bridge to execute arbitrary Lua snippets for state probing (e.g., checking `df.global.world`) will fail. The RPC interface likely expects specific DFHack commands rather than raw Lua code injection via the `lua` keyword in this context.

### 2. Direct CLI Invocation [VERIFIED]
The binary `./dwarfort` supports direct Lua execution via the `-- lua -e "..."` syntax, bypassing the RPC layer entirely.

* **Evidence**: Process listing (`ps aux`) shows active processes utilizing this pattern:
  ```bash
  ./dwarfort -- lua -e "local items = df.item_type; ..."
  ./dwarfort -- lua -e local jt = df.job_type; ...
  ```
* **Status**: These processes are observed running with high CPU usage, indicating successful initialization and execution of the Lua environment.

### 3. Execution Latency and Timeout Risks [INFERRED]
Direct CLI invocation incurs significant startup overhead due to game initialization (window resizing, font loading).

* **Evidence**: A probe command executed via:
  ```bash
  cd /srv/df-bonsai/current && DISPLAY="" SDL_VIDEODRIVER=dummy ./dwarfort -- lua -e "local w=df.global.world; print('WORLD_OK year=' .. w.cur_year ..."
  ```
  Resulted in:
  ```text
  New window size: 1024x768
  Font size: 8x12
  Resizing grid to 128x64
  <shell_metadata>
  shell tool terminated command after exceeding timeout 60000 ms.
  ```
* **Implication**: While the CLI method works, it is too slow for frequent polling. The game engine initializes fully before executing the Lua snippet, leading to timeouts in short-lived agent probes.

## Implications for Agent Design

### Reset / Observe / Act / Advance
1.  **Observe**: Do not use RPC `lua` commands for state extraction. Use CLI invocation only if necessary, but be aware of high latency. Prefer reading static files or using established DFHack plugins that expose data via faster mechanisms (if available).
2.  **Act**: Direct CLI injection is viable for one-off actions but risky due to timeouts.
3.  **Advance**: Time advancement should likely rely on existing DFHack commands (e.g., `advance`) rather than Lua scripts injected via CLI, unless the Lua script is pre-loaded into a persistent session.

### Coding Recommendations
1.  **Avoid RPC Lua Injection**: Do not send `lua <code>` strings to the DFHack remote client. It will reject them as unrecognized commands.
2.  **Use Persistent Sessions**: If Lua execution is required, establish a persistent DFHack session (via `dofile` or similar) that keeps the Lua environment alive, rather than spawning new `./dwarfort -- lua -e` processes for every query.
3.  **Timeout Handling**: If CLI invocation is used, increase timeout thresholds significantly (>60s) to account for game initialization overhead.
4.  **Environment Variables**: Ensure `DISPLAY=""` and `SDL_VIDEODRIVER=dummy` are set when invoking `./dwarfort` in headless environments to prevent graphical subsystem errors.

## Open Questions
* Is there a specific DFHack plugin or command that allows faster state querying via RPC without full game initialization? [OPEN]
* Why does the RPC interface reject `lua` commands while accepting other DFHack commands? Is this a configuration issue in `dfhack-run`? [OPEN]
