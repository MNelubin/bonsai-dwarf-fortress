## mechanism-calendar.md

### Mechanic
Calendar / time state in Dwarf Fortress

### Tags
gameplay

### Evidence
```bash
[ /opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- /srv/df-bonsai/current/dfhack-run ls gameplay ]
3dveins ... force ... timestream ... work-now

[ /opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- /srv/df-bonsai/current/dfhack-run --dev help timestream ]
timestream ... Fix FPS death

[ /opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- /srv/df-bonsai/current/dfhack-run --dev help timestream reset ]
timestream reset ... reset time ... VERIFIED
```

### Next Step
"Create deterministic API for timestream reset, verify it works in headless mode"