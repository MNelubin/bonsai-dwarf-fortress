## Pause Mechanic Discovery

**Source:** `pause` command probe in DFHack
**Status:** VERIFIED
**Command:** `dfhack-run help pause`
**Result:** No dedicated pause command exists in DFHack. The closest match is **fpause** - Force DF to pause.

### Key finding
DFHack does not implement a direct `pause` command. Instead, the pause functionality is accessed through: `fpause` - Force Dwarf Fortress to pause.

This indicates that DFHack abstracts pause functionality through the `fpause` command for programmatic pausing control.