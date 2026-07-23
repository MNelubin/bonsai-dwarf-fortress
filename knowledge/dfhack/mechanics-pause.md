# pause mechanic

**Claim**: DFHack provides `fpause` command to forcibly pause Dwarf Fortress.
**Status**: VERIFIED
**Source**: `/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- dfhack-run lua <<EOF
print(dfhack.getdate())
EOF`
**Result**:
```
BONSAI_PROBE_RESULT {
  "exit":0,
  "timed_out":false,
  "duration_seconds":0.037,
  "command":["/srv/df-bonsai/.../dfhack-run","lua"],
  "runtime_ready":true,
  "runtime":{"...
  "output":"\u001b[0m...\n  fpause               - Force DF to pause.\n  ..."
}}
```

**Implementation Gap**: No API wrapper for `fpause` exists in bridge/, tests/.
**Next Step**: Create deterministic API with `pause/confirm` command to freeze and resume DF.
**Test Plan**: Write test that asserts DFHack state remains consistent after pausing.
