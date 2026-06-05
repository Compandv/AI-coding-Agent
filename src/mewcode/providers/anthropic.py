from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx

from mewcode.config import MewCodeConfig
from mewcode.session import Message

from .base import ChatProvider, ChatResponse, StreamChunk, ToolCall
from .errors import ProviderError
from .sse import SSEClientMixin


def parse_anthropic_tool_calls_stream(events: list[dict[str, Any]]) -> list[ToolCall]:
    tool_calls_by_index: dict[int, dict[str, Any]] = {}
    current_index = 0
    for event in events:
        if event.get("type") == "content_block_start":
            raw_index = event.get("index")
            current_index = int(raw_index) if raw_index is not None else len(tool_calls_by_index)
            block = event.get("content_block") or {}
            if block.get("type") == "tool_use":
                tool_calls_by_index[current_index] = {
                    "id": str(block.get("id") or f"toolu_{current_index}"),
                    "name": str(block.get("name", "")),
                    "input": block.get("input") or {},
                    "partials": [],
                }
        elif event.get("type") == "content_block_delta":
            raw_index = event.get("index")
            index = int(raw_index) if raw_index is not None else current_index
            delta = event.get("delta") or {}
            if delta.get("type") == "input_json_delta":
                entry = tool_calls_by_index.setdefault(
                    index,
                    {"id": f"toolu_{index}", "name": "", "input": {}, "partials": []},
                )
                entry["partials"].append(str(delta.get("partial_json") or ""))

    tool_calls: list[ToolCall] = []
    for index in sorted(tool_calls_by_index):
        entry = tool_calls_by_index[index]
        name = str(entry.get("name") or "")
        if not name:
            continue
        partials = entry.get("partials") or []
        if partials:
            try:
                arguments = json.loads("".join(partials))
            except json.JSONDecodeError as exc:
                raise ProviderError(f"Invalid anthropic tool call JSON: {exc}") from exc
        else:
            arguments = entry.get("input") or {}
        tool_calls.append(ToolCall(name=name, arguments=arguments, id=str(entry.get("id") or f"toolu_{index}")))
    return tool_calls


def parse_anthropic_tool_call_stream(events: list[dict[str, Any]]) -> ToolCall | None:
    tool_calls = parse_anthropic_tool_calls_stream(events)
    return tool_calls[0] if tool_calls else None


class AnthropicProvider(SSEClientMixin, ChatProvider):
    def __init__(self, config: MewCodeConfig, client: httpx.Client | None = None) -> None:
        self.config = config
        self.client = client or httpx.Client(timeout=config.timeout_seconds)

    def stream_chat(self, messages: list[Message]) -> Iterator[str]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": self._messages_payload(messages),
            "stream": True,
            "max_tokens": int(self.config.extra.get("max_tokens", 4096)),
        }
        thinking = self._thinking_payload()
        if thinking:
            payload["thinking"] = thinking

        headers = {
            "x-api-key": self.config.api_key,
            "anthropic-version": str(self.config.extra.get("anthropic_version", "2023-06-01")),
            "content-type": "application/json",
            "accept": "text/event-stream",
        }

        url = f"{self.config.base_url}/v1/messages"
        try:
            with self.client.stream("POST", url, headers=headers, json=payload) as response:
                self._raise_for_status(response)
                for event in self._iter_sse_json(response):
                    text = self._text_delta(event)
                    if text:
                        yield text
        except httpx.HTTPError as exc:
            raise ProviderError(f"Network or connection failed: {exc}") from exc

    def complete_chat(self, messages: list[Message], tools: list[dict[str, Any]] | None = None) -> ChatResponse:
        if tools:
            return self._complete_chat_with_tools_stream(messages, tools)
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": self._messages_payload(messages),
            "stream": False,
            "max_tokens": int(self.config.extra.get("max_tokens", 4096)),
        }
        thinking = self._thinking_payload()
        if thinking:
            payload["thinking"] = thinking

        headers = {
            "x-api-key": self.config.api_key,
            "anthropic-version": str(self.config.extra.get("anthropic_version", "2023-06-01")),
            "content-type": "application/json",
        }
        url = f"{self.config.base_url}/v1/messages"
        try:
            response = self.client.post(url, headers=headers, json=payload)
            self._raise_for_status(response)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Network or connection failed: {exc}") from exc

        data = response.json()
        text = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
        return ChatResponse(text=text)

    def stream_response(
        self, messages: list[Message], tools: list[dict[str, Any]] | None = None
    ) -> Iterator[StreamChunk]:
        if not tools:
            for text in self.stream_chat(messages):
                yield StreamChunk(text=text)
            return

        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": self._messages_payload(messages),
            "stream": True,
            "max_tokens": int(self.config.extra.get("max_tokens", 4096)),
            "tools": tools,
        }
        thinking = self._thinking_payload()
        if thinking:
            payload["thinking"] = thinking

        headers = {
            "x-api-key": self.config.api_key,
            "anthropic-version": str(self.config.extra.get("anthropic_version", "2023-06-01")),
            "content-type": "application/json",
            "accept": "text/event-stream",
        }
        url = f"{self.config.base_url}/v1/messages"
        events: list[dict[str, Any]] = []
        try:
            with self.client.stream("POST", url, headers=headers, json=payload) as response:
                self._raise_for_status(response)
                for event in self._iter_sse_json(response):
                    events.append(event)
                    text = self._text_delta(event)
                    if text:
                        yield StreamChunk(text=text)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Network or connection failed: {exc}") from exc

        tool_calls = parse_anthropic_tool_calls_stream(events)
        if tool_calls:
            yield StreamChunk(tool_calls=tool_calls)

    def _complete_chat_with_tools_stream(self, messages: list[Message], tools: list[dict[str, Any]]) -> ChatResponse:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": self._messages_payload(messages),
            "stream": True,
            "max_tokens": int(self.config.extra.get("max_tokens", 4096)),
            "tools": tools,
        }
        thinking = self._thinking_payload()
        if thinking:
            payload["thinking"] = thinking

        headers = {
            "x-api-key": self.config.api_key,
            "anthropic-version": str(self.config.extra.get("anthropic_version", "2023-06-01")),
            "content-type": "application/json",
            "accept": "text/event-stream",
        }
        url = f"{self.config.base_url}/v1/messages"
        events: list[dict[str, Any]] = []
        text_parts: list[str] = []
        try:
            with self.client.stream("POST", url, headers=headers, json=payload) as response:
                self._raise_for_status(response)
                for event in self._iter_sse_json(response):
                    events.append(event)
                    text = self._text_delta(event)
                    if text:
                        text_parts.append(text)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Network or connection failed: {exc}") from exc

        tool_calls = parse_anthropic_tool_calls_stream(events)
        if tool_calls:
            return ChatResponse(text="", tool_calls=tool_calls)
        return ChatResponse(text="".join(text_parts))

    def _messages_payload(self, messages: list[Message]) -> list[dict[str, Any]]:
        payload = []
        for message in messages:
            role = message["role"]
            if role == "tool":
                payload.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": str(message.get("tool_id") or message.get("tool_name", "tool")),
                                "content": json.dumps(message.get("tool_result", {})),
                            }
                        ],
                    }
                )
            elif "tool_calls" in message:
                payload.append(
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": str(tool_call.get("id") or tool_call.get("name", "tool")),
                                "name": str(tool_call.get("name", "tool")),
                                "input": tool_call.get("arguments", {}),
                            }
                            for tool_call in message.get("tool_calls", [])
                        ],
                    }
                )
            elif "tool_input" in message:
                payload.append(
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": str(message.get("tool_id") or message.get("tool_name", "tool")),
                                "name": str(message.get("tool_name", "tool")),
                                "input": message.get("tool_input", {}),
                            }
                        ],
                    }
                )
            else:
                payload.append({"role": role, "content": message.get("content", "")})
        return payload

    def _thinking_payload(self) -> dict[str, Any] | None:
        thinking = self.config.thinking
        if not thinking.get("enabled"):
            return None
        payload: dict[str, Any] = {"type": "enabled"}
        if "budget_tokens" in thinking:
            payload["budget_tokens"] = thinking["budget_tokens"]
        return payload

    def _text_delta(self, event: dict[str, Any]) -> str:
        if event.get("type") == "content_block_delta":
            delta = event.get("delta") or {}
            if delta.get("type") == "text_delta":
                return str(delta.get("text") or "")
        return ""

    def _raise_for_status(self, response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if response.status_code in {401, 403}:
                raise ProviderError("Authentication failed. Check your API key.") from exc
            raise ProviderError(f"Provider request failed with HTTP {response.status_code}.") from exc
