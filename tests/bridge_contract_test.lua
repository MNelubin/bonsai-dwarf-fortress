-- tests/bridge_contract_test.lua
-- Deterministic public tests for Bridge contract.

local contract = require "bridge.contract"

-- Reset test.
local reset_res = contract.reset()
assert(reset_res.status == "reset", "Reset test failed: expected status 'reset'")

-- Observe test.
local observe_res = contract.observe()
assert(observe_res.status == "ok", "Observe test failed: expected status 'ok'")
assert(observe_res.timestamp == 0, "Observe test failed: expected timestamp 0")
assert(observe_res.state == "idle", "Observe test failed: expected state 'idle'")

-- Act test.
local sample_action = {type = "move", direction = "north"}
local act_res = contract.act(sample_action)
assert(act_res.status == "ok", "Act test failed: expected status 'ok'")
assert(act_res.performed.type == sample_action.type, "Act test failed: performed.type mismatch")
assert(act_res.performed.direction == sample_action.direction, "Act test failed: performed.direction mismatch")

-- Advance test.
local step = 7
local advance_res = contract.advance(step)
assert(advance_res.status == "ok", "Advance test failed: expected status 'ok'")
assert(advance_res.advanced == step, "Advance test failed: advanced step mismatch")

print("All Bridge contract tests passed.")