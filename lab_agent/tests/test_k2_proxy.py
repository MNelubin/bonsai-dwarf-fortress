from bonsai_lab_agent.k2_proxy import TOKEN_LIMIT_FIELDS, transform_request


def test_transform_request_strips_all_output_limits_and_preserves_low_reasoning():
    payload = {
        "model": "MBZUAI-IFM/K2-Think-v2",
        "messages": [{"role": "user", "content": "hello"}],
        "stream": True,
        "reasoning_effort": "low",
        "max_tokens": 1,
        "max_completion_tokens": 2,
        "max_output_tokens": 3,
        "maxTokens": 4,
    }
    transformed = transform_request(payload)
    assert transformed["reasoning_effort"] == "low"
    assert transformed["stream"] is True
    assert all(field not in transformed for field in TOKEN_LIMIT_FIELDS)
    assert payload["max_tokens"] == 1


def test_transform_request_preserves_explicit_medium_for_bounded_repair():
    transformed = transform_request(
        {
            "model": "MBZUAI-IFM/K2-Think-v2",
            "messages": [{"role": "user", "content": "repair this validated diff"}],
            "reasoning_effort": "medium",
            "max_tokens": 1,
        }
    )
    assert transformed["reasoning_effort"] == "medium"
    assert all(field not in transformed for field in TOKEN_LIMIT_FIELDS)


def test_transform_request_preserves_tools_and_response_format():
    payload = {
        "model": "MBZUAI-IFM/K2-Think-v2",
        "tools": [{"type": "function", "function": {"name": "read", "parameters": {}}}],
        "response_format": {"type": "json_object"},
    }
    transformed = transform_request(payload)
    assert transformed["tools"] == payload["tools"]
    assert transformed["response_format"] == payload["response_format"]


def test_transform_request_removes_unsupported_reasoning_from_assistant_history():
    payload = {
        "messages": [
            {"role": "user", "content": "use a tool"},
            {
                "role": "assistant",
                "content": "",
                "reasoning_content": "private chain",
                "reasoning": "alternate private chain",
                "tool_calls": [{"id": "call-1", "type": "function"}],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": "ok"},
        ]
    }
    transformed = transform_request(payload)
    assistant = transformed["messages"][1]
    assert "reasoning_content" not in assistant
    assert "reasoning" not in assistant
    assert assistant["tool_calls"] == payload["messages"][1]["tool_calls"]
    assert transformed["messages"][2] == payload["messages"][2]
