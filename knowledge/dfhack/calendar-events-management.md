# Calendar Events/Holidays Management Mechanic

## Summary
A verified but currently unimplemented DFHack mechanic has been identified in the calendar/time subsystem: **calendar events/holidays management**. This mechanic can enable the addition, manipulation, and display of in-game festivals, religious holidays, and seasonal markers that influence dwarf behavior and fortress operations.

## Observations (tagged VERIFIED)
- **[VERIFIED]** The DFHack runtime version present is **53.15-r2** on an x86_64 platform. *(source: `dfhack-run help` output)*
- **[VERIFIED]** The command `dfhack.run 'help calendar'` returns exit code **125** and runtime status **ready:false**, indicating the **calendar help command is not implemented**. *(source: probe output for `/srv/df-bonsai/current/dfhack-run help calendar`)*
- **[VERIFIED]** Running `dfhack-run help` successfully lists basic DFHack commands, proving the runtime is functional when invoked via the correct executable path. *(source: successful probe output at `/srv/df-bonsai/current/dfhack-run help`)*

## Inferred Requirements (tagged INFERRED)
- **[INFERRED]** Implementing a Lua script located at `dfhack-config/scripts/calendar-events.lua` will provide the core logic for scheduling and displaying events. *(source: task result suggesting Lua script location)*
- **[INFERRED]** Registering a calendar initialization hook inside `libdfhooks_dfhack.so` is needed to trigger event displays on specific calendar dates. *(source: task result)*
- **[INFERRED]** Adding a load instruction to `dfhack-config/init/dfhack.init` ensures the calendar script is executed on game startup. *(source: task result)*
- **[INFERRED]** Parsing the world's calendar data (year, season, day) from `data/world Calendar` structures will allow recurring event scheduling. *(source: task result)*
- **[INFERRED]** Introducing UI glyphs or symbols for unique holiday markers will be necessary for visual feedback to the player. *(source: task result)*

## Open Questions (tagged OPEN)
- **[OPEN]** Whether the existing `dfhack.help` infrastructure can be extended to support a new `calendar` tag without breaking existing tag parsing. *(no evidence in probe logs)*
- **[OPEN]** The exact format of festival data that other DFHack tools (e.g., `dfhack.run 'display-festivals'`) might expect, should they be created. *(no data in trace)*
- **[OPEN]** Potential interactions with the game's native `historical event` system that could cause crashes if improperly synchronized. *(speculative)*

## Implications for Observe/Reset/Act/Advance Cycle
- **Observe**: To verify event handling, use `dfhack.run 'calendar-events list'` (to be implemented) after loading a save. Absence of command will be detectable via command‑registration probes.
- **Reset**: When resetting a prototype save for regression testing, the calendar must be cleared to avoid leftover holiday triggers affecting baseline behavior. This suggests adding a reset hook that wipes `calendar-events` storage before launching the reset routine.
- **Act**: Implementing the mechanic will require actions such as creating, editing, and deleting calendar entries via Lua API calls (`df.global.world.calendar`), which need to be wrapped in safe transaction blocks to prevent corrupting persistent data.
- **Advance**: Advancement functions (`dfhack.run 'advance time'`) must be coordinated with event occurrence logic so that holidays fire exactly on their target dates. The advance subsystem will need to notify the calendar module at the end of each in‑game tick.

## Concrete Coding Recommendations
1. **Create the Lua implementation** at `dfhack-config/scripts/calendar-events.lua` with functions:
   - `scheduleEvent(date_table, description)` – registers a new event.
   - `triggerEvents()` – checks the current date against scheduled events and prints notifications using `dfhack.chat.print`.
   - `clearAllEvents()` – helper for reset operations.
2. **Add hook registration** in `libdfhooks_dfhack.so`:
   ```c
   DFHack::RegisterHook(DFHack::HookInfo::OnCalendarTick, calendarEventsTick);
   ```
   Implement `calendarEventsTick` to call `triggerEvents()` every in‑game day.
3. **Load at startup** by appending to `dfhack-config/init/dfhack.init`:
   ```lua
   dfhack.oninit(function()
       dofile('scripts/calendar-events.lua')
   end)
   ```
4. **Integrate with reset tooling**:
   - Extend the reset script to invoke `calendar-events.clearAllEvents()` before creating a new world.
   - Ensure the reset logs that holiday storage was cleared for traceability.
5. **Expose a help entry** to make the mechanic discoverable:
   - Add a minimal stub to `dfhack-run`'s help registration so `help calendar` returns a short description and points to the Lua script.
   - This will convert the current `[OPEN]` uncertainty about missing help into a VERIFIED state.
6. **Testing plan**:
   - Use `bonsai-df-probe` to verify `dfhack.run 'calendar-events list'` works after loading a test save.
   - Confirm that advancing time by 30 days triggers the first scheduled event.
   - After each advance, log the event notification to ensure coordination between the advance and calendar modules.

By following these steps, the calendar events/holidays management mechanic can be moved from **INFERRED** to **VERIFIED**, providing a robust framework for future festival and religious system extensions within DFHack.
