import json

import httpx

from mewcode.config import MewCodeConfig
from mewcode.providers.anthropic import (
    AnthropicProvider,
    parse_anthropic_tool_call_stream,
    parse_anthropic_tool_calls_stream,
)
from mewcode.providers.base import ToolCall
from mewcode.providers.openai import OpenAIProvider, parse_openai_tool_call_stream, parse_openai_tool_calls_stream


def make_response(events):
    body = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
    return httpx.Response(200, content=body.encode("utf-8"))


def test_anthropic_streams_text_and_sends_thinking():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = request.headers
        captured["json"] = json.loads(request.content)
        return make_response([
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "he"}},
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "llo"}},
        ])

    config = MewCodeConfig(
        protocol="anthropic",
        model="claude-sonnet-4-6",
        base_url="https://api.anthropic.com",
        api_key="sk-ant-placeholder",
        thinking={"enabled": True, "budget_tokens": 1024},
    )
    provider = AnthropicProvider(config, client=httpx.Client(transport=httpx.MockTransport(handler)))

    chunks = list(provider.stream_chat([{"role": "user", "content": "hello"}]))

    assert chunks == ["he", "llo"]
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "sk-ant-placeholder"
    assert captured["json"]["model"] == "claude-sonnet-4-6"
    assert captured["json"]["thinking"] == {"type": "enabled", "budget_tokens": 1024}


def test_anthropic_omits_disabled_thinking():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json.loads(request.content)
        return make_response([])

    config = MewCodeConfig(
        protocol="anthropic",
        model="claude-sonnet-4-6",
        base_url="https://api.anthropic.com",
        api_key="sk-ant-placeholder",
        thinking={"enabled": False},
    )
    provider = AnthropicProvider(config, client=httpx.Client(transport=httpx.MockTransport(handler)))

    list(provider.stream_chat([{"role": "user", "content": "hello"}]))

    assert "thinking" not in captured["json"]


def test_anthropic_complete_chat_returns_tool_call():
    def handler(request: httpx.Request) -> httpx.Response:
        return make_response([
            {"type": "content_block_start", "content_block": {"type": "tool_use", "name": "ReadFile"}},
            {"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": "{\"path\":"}},
            {"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": " \"README.md\"}"}},
        ])

    config = MewCodeConfig(
        protocol="anthropic",
        model="claude-sonnet-4-6",
        base_url="https://api.anthropic.com",
        api_key="sk-ant-placeholder",
    )
    provider = AnthropicProvider(config, client=httpx.Client(transport=httpx.MockTransport(handler)))

    response = provider.complete_chat([{"role": "user", "content": "read readme"}], tools=[{"name": "ReadFile"}])

    assert response.tool_call == ToolCall(name="ReadFile", arguments={"path": "README.md"}, id="toolu_0")
    assert response.tool_calls == [ToolCall(name="ReadFile", arguments={"path": "README.md"}, id="toolu_0")]


def test_anthropic_tool_call_stream_parses_json_fragments():
    events = [
        {"type": "content_block_start", "content_block": {"type": "tool_use", "name": "ReadFile"}},
        {"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": "{\"path\":"}},
        {"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": " \"README.md\"}"}},
    ]

    assert parse_anthropic_tool_call_stream(events) == ToolCall(
        name="ReadFile",
        arguments={"path": "README.md"},
        id="toolu_0",
    )


def test_anthropic_tool_calls_stream_parses_multiple_tool_use_blocks():
    events = [
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "tool_use", "id": "read_a", "name": "ReadFile"},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": "{\"path\": \"a.txt\"}"},
        },
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {"type": "tool_use", "id": "read_b", "name": "ReadFile"},
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": "{\"path\": \"b.txt\"}"},
        },
    ]

    assert parse_anthropic_tool_calls_stream(events) == [
        ToolCall(name="ReadFile", arguments={"path": "a.txt"}, id="read_a"),
        ToolCall(name="ReadFile", arguments={"path": "b.txt"}, id="read_b"),
    ]


def test_openai_streams_text_and_ignores_thinking():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = request.headers
        captured["json"] = json.loads(request.content)
        return make_response([
            {"choices": [{"delta": {"content": "he"}}]},
            {"choices": [{"delta": {"content": "llo"}}]},
        ])

    config = MewCodeConfig(
        protocol="openai",
        model="gpt-4.1",
        base_url="https://api.openai.com/v1",
        api_key="sk-placeholder",
        thinking={"enabled": True, "budget_tokens": 1024},
    )
    provider = OpenAIProvider(config, client=httpx.Client(transport=httpx.MockTransport(handler)))

    chunks = list(provider.stream_chat([{"role": "user", "content": "hello"}]))

    assert chunks == ["he", "llo"]
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured["headers"]["authorization"] == "Bearer sk-placeholder"
    assert captured["json"]["model"] == "gpt-4.1"
    assert "thinking" not in captured["json"]


def test_openai_complete_chat_returns_tool_call():
    def handler(request: httpx.Request) -> httpx.Response:
        return make_response([
            {"choices": [{"delta": {"tool_calls": [{"function": {"name": "ReadFile", "arguments": "{\"path\":"}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"function": {"arguments": " \"README.md\"}"}}]}}]},
        ])

    config = MewCodeConfig(
        protocol="openai",
        model="gpt-4.1",
        base_url="https://api.openai.com/v1",
        api_key="sk-placeholder",
    )
    provider = OpenAIProvider(config, client=httpx.Client(transport=httpx.MockTransport(handler)))

    response = provider.complete_chat([{"role": "user", "content": "read readme"}], tools=[{"name": "ReadFile"}])

    assert response.tool_call == ToolCall(name="ReadFile", arguments={"path": "README.md"}, id="call_0")
    assert response.tool_calls == [ToolCall(name="ReadFile", arguments={"path": "README.md"}, id="call_0")]


def test_openai_tool_call_stream_uses_first_tool_call_index():
    events = [
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "function": {"name": "ReadFile", "arguments": "{\"path\":"}},
                            {"index": 1, "function": {"name": "Bash", "arguments": "{\"command\":"}},
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "function": {"arguments": " \"README.md\"}"}},
                            {"index": 1, "function": {"arguments": " \"pwd\"}"}},
                        ]
                    }
                }
            ]
        },
    ]

    assert parse_openai_tool_call_stream(events) == ToolCall(
        name="ReadFile",
        arguments={"path": "README.md"},
        id="call_0",
    )
    assert parse_openai_tool_calls_stream(events) == [
        ToolCall(name="ReadFile", arguments={"path": "README.md"}, id="call_0"),
        ToolCall(name="Bash", arguments={"command": "pwd"}, id="call_1"),
    ]


def test_openai_tool_calls_stream_preserves_provider_ids_and_order():
    events = [
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "read_a",
                                "function": {"name": "ReadFile", "arguments": "{\"path\":"},
                            },
                            {
                                "index": 1,
                                "id": "read_b",
                                "function": {"name": "ReadFile", "arguments": "{\"path\":"},
                            },
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "function": {"arguments": " \"a.txt\"}"}},
                            {"index": 1, "function": {"arguments": " \"b.txt\"}"}},
                        ]
                    }
                }
            ]
        },
    ]

    assert parse_openai_tool_calls_stream(events) == [
        ToolCall(name="ReadFile", arguments={"path": "a.txt"}, id="read_a"),
        ToolCall(name="ReadFile", arguments={"path": "b.txt"}, id="read_b"),
    ]


def test_openai_sends_parameters_not_input_schema():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json.loads(request.content)
        return make_response([
            {"choices": [{"delta": {"tool_calls": [{"function": {"name": "Glob", "arguments": "{\"pattern\":"}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"function": {"arguments": " \"**/*.py\"}"}}]}}]},
        ])

    config = MewCodeConfig(
        protocol="openai",
        model="gpt-4.1",
        base_url="https://api.openai.com/v1",
        api_key="sk-placeholder",
    )
    provider = OpenAIProvider(config, client=httpx.Client(transport=httpx.MockTransport(handler)))

    tools = [
        {
            "name": "Glob",
            "description": "Find files matching a pattern",
            "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]},
        }
    ]
    list(provider.stream_response([{"role": "user", "content": "find files"}], tools=tools))

    assert "tools" in captured["json"]
    assert captured["json"]["tools"][0]["type"] == "function"
    assert captured["json"]["tools"][0]["function"]["name"] == "Glob"
    assert "parameters" in captured["json"]["tools"][0]["function"]
    assert "input_schema" not in captured["json"]["tools"][0]["function"]
    assert captured["json"]["tools"][0]["function"]["parameters"]["required"] == ["pattern"]
