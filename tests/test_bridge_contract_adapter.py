# tests/test_bridge_contract_adapter.py
# Static verification that bridge/contract.lua is a thin adapter over bridge.core.

# import pytest
from pathlib import Path

CONTRACT_PATH = Path(__file__).parent.parent / 'bridge' / 'contract.lua'

def test_contract_is_adapter():
    # Check that contract imports bridge.core.
    content = CONTRACT_PATH.read_text(encoding='utf-8')
    assert "local core = require('bridge.core')" in content, 'Missing bridge.core import'
    # Ensure no placeholder return values from the old implementation.
    for placeholder in ['status', 'timestamp', 'state', 'performed', 'advanced']:
        assert placeholder not in content, f"Placeholder '{placeholder}' still present"
    # Verify delegation calls.
    assert "core.reset()" in content, 'reset must delegate to core.reset'
    assert "core.observe()" in content, 'observe must delegate to core.observe'
    assert "M.act(" in content and "core.act" in content, 'act must delegate to core.act'
    assert "M.advance(" in content and "core.advance" in content, 'advance must delegate to core.advance'