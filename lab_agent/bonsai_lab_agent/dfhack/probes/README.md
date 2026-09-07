# One-off probes

Research scripts written to answer a single question about a live fort — why a job was
cancelled, what the geology looks like, which orders the manager holds. None of them is
called by the runtime, by the evaluator, or by a test.

They live here rather than beside the runtime scripts so that the directory the agent
actually depends on lists only what actually runs:

    bonsai_session.sh      boot / load / prep a fort, in phases
    bonsai-observe.lua     the ground-truth observation
    bonsai-apply-actions.lua  the action dispatcher
    bonsai-advance2.lua    advance exactly N ticks
    bonsai-reach.lua       reachability, used by the dispatcher
    bonsai-nowild.lua      wildlife suppression (debug determinism only)
    bonsai-headless-init.lua, click-text.lua, click-row.lua   boot plumbing
    bonsai-map-capture.lua, bonsai-dump-enums.lua             replay viewer
    bonsai-eval-state.lua, bonsai-roomvalue.lua               evaluator and design search

Because they are outside the `dfhack/*.lua` package-data glob they are NOT installed with
the wheel and cannot be invoked by name on the lab host. Copy the one you need across for
the run that needs it; that is the point, not an oversight.

Kept, not deleted: each one encodes a question that turned out to be worth asking, and
several of them are how the water table, the dig stalls and the order queue were measured.
