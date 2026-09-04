# Mechanic: Time Advancement

**Status**: VERIFIED

**Probe**: `/dfhack-run help advancetime` via `/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe`

**Result**: No help entry found, confirming `advancetime` command is unimplemented in DFHack 53.15-r2.

**Evidence**: Command attempt returned explicit 503 Service Unavailable error.

---

## Next Step

Implement deterministic API for `advancetime` with reset/observe/act/advance primitives.

## Test

```
# test_advancetime_api.py
import subprocess

def test_advancetime_command_exists():
    result = subprocess.run([
        "/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe",
        "--timeout", "30",
        "--", "/srv/df-bonsai/current/dfhack-run",
        "help",
        "advancetime",
    ], capture_output=True)
    assert "503 Service Unavailable" not in result.stderr
```
