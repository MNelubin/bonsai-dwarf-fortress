-- tests/bridge_contract_test.lua
-- Deterministic delegation tests for the Bridge contract using a fake bridge.core module.

local core_calls = {
    reset = 0,
    observe = 0,
    act = 0,
    advance = 0,
}
local core_last = {
    act = nil,
    advance_ticks = nil,
}

-- Fake bridge.core module that records calls and returns deterministic values.
local fake_core = {
    reset = function()
        core_calls.reset = core_calls.reset + 1
        return true
    end,
    observe = function()
        core_calls.observe = core_calls.observe + 1
        return { version = '1.0', gametype = 'fake', cur_year = 123, cur_season = 4, cur_tick = 5000, paused = false }
    end,
    act = function(action)
        core_calls.act = core_calls.act + 1
        core_last.act = action
        return { ok = true, message = 'action dispatched', output = nil }
    end,
    advance = function(ticks)
        core_calls.advance = core_calls.advance + 1
        core_last.advance_ticks = ticks
        return { ok = true, advanced_ticks = ticks }
    end,
}

-- Inject the fake core before requiring the contract.
package.loaded['bridge.core'] = fake_core

local contract = require 'bridge.contract'

-- Helper to capture core call counts before each test.
local function reset_counters()
    core_calls.reset = 0
    core_calls.observe = 0
    core_calls.act = 0
    core_calls.advance = 0
    core_last.act = nil
    core_last.advance_ticks = nil
end

-- Reset test.
reset_counters()
local reset_res = contract.reset()
assert(reset_res == nil, 'reset should return nil')
assert(core_calls.reset == 1, 'reset called core.reset once')

-- Observe test.
reset_counters()
local observe_res = contract.observe()
assert(type(observe_res) == 'table', 'observe should return a table')
assert(core_calls.observe == 1, 'observe called core.observe once')
assert(observe_res.version == '1.0', 'observe result version mismatch')
assert(observe_res.gametype == 'fake', 'observe result gametype mismatch')

-- Act test: invalid type (not a table).
reset_counters()
local act_err_type = contract.act('string')
assert(type(act_err_type) == 'table', 'act error should be a table')
assert(act_err_type.ok == false and #act_err_type.message > 0, 'act error for non-table input should have ok = false')
assert(core_calls.act == 0, 'act with invalid type should not call core.act')

-- Act test: missing command field.
reset_counters()
local action_missing = { args = {} }
local act_err_missing = contract.act(action_missing)
assert(type(act_err_missing) == 'table')
assert(act_err_missing.ok == false and #act_err_missing.message > 0, 'act error for missing command should have ok = false')
assert(core_calls.act == 0, 'act with missing command should not call core.act')

-- Act test: valid action.
reset_counters()
local action_valid = { command = 'pause', args = { 'immediately' } }
local act_res_valid = contract.act(action_valid)
assert(type(act_res_valid) == 'table')
assert(act_res_valid.ok == true, 'valid act should have ok = true')
assert(core_calls.act == 1, 'valid act should call core.act once')
assert(core_last.act.name == 'pause', 'core.act received name mismatch')
assert(core_last.act.args == action_valid.args, 'core.act args unchanged')

-- Advance test: invalid (zero ticks).
reset_counters()
local adv_err_zero = contract.advance(0)
assert(type(adv_err_zero) == 'table')
assert(adv_err_zero.ok == false and #adv_err_zero.message > 0, 'advance zero ticks error should have ok = false')
assert(core_calls.advance == 0, 'advance with zero ticks should not call core.advance')

-- Advance test: non-number input.
reset_counters()
local adv_err_str = contract.advance('seven')
assert(type(adv_err_str) == 'table')
assert(adv_err_str.ok == false and #adv_err_str.message > 0, 'advance non-number error should have ok = false')
assert(core_calls.advance == 0, 'advance with non-number should not call core.advance')

-- Advance test: valid positive tick value.
reset_counters()
local step = 42
local adv_res_valid = contract.advance(step)
assert(type(adv_res_valid) == 'table')
assert(adv_res_valid.ok == true, 'valid advance should have ok = true')
assert(core_calls.advance == 1, 'valid advance should call core.advance once')
assert(core_last.advance_ticks == step, 'advance forwarded ticks unchanged')

print('All Bridge contract delegation tests passed.')