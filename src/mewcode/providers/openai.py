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


def parse_openai_tool_calls_stream(events: list[dict[str, Any]]) -> list[ToolCall]:
    tool_calls_by_index: dict[int, dict[str, Any]] = {}
    for event in events:
        choices = event.get("choices") or []
        if not choices:
            continue
        delta = choices[0].get("delta") or {}
        tool_calls = delta.get("tool_calls") or []
        for fallback_index, tool_call in enumerate(tool_calls):
            index = tool_call.get("index")
            if index is None:
                index = fallback_index
            entry = tool_calls_by_index.setdefault(int(index), {"id": None, "name": None, "arguments": []})
            if tool_call.get("id"):
                entry["id"] = str(tool_call["id"])
            function = tool_call.get("function") or {}
            if function.get("name"):
                entry["name"] = str(function["name"])
            if function.get("arguments") is not None:
                entry["arguments"].append(str(function["arguments"]))
    if not tool_calls_by_index:
        return []

    tool_calls: list[ToolCall] = []
    for index in sorted(tool_calls_by_index):
        entry = tool_calls_by_index[index]
        current_name = entry["name"]
        if current_name is None:
            continue
        try:
            arguments = json.loads("".join(entry["arguments"]).strip() or "{}")
        except json.JSONDecodeError as exc:
            raise ProviderError(f"Invalid openai tool call JSON: {exc}") from exc
        tool_calls.append(ToolCall(name=current_name, arguments=arguments, id=entry["id"] or f"call_{index}"))
    return tool_calls


def parse_openai_tool_call_stream(events: list[dict[str, Any]]) -> ToolCall | None:
    tool_calls = parse_openai_tool_calls_stream(events)
    return tool_calls[0] if tool_calls else None


class OpenAIProvider(SSEClientMixin, ChatProvider):
    def __init__(self, config: MewCodeConfig, client: httpx.Client | None = None) -> None:
        self.config = config
        self.client = client or httpx.Client(timeout=config.timeout_seconds)

    def stream_chat(self, messages: list[Message]) -> Iterator[str]:
        payload = {
            "model": self.config.model,
            "messages": self._messages_payload(messages),
            "stream": True,
        }
        if "max_tokens" in self.config.extra:
            payload["max_tokens"] = self.config.extra["max_tokens"]

        headers = {
            "authorization": f"Bearer {self.config.api_key}",
            "content-type": "application/json",
            "accept": "text/event-stream",
        }

        url = f"{self.config.base_url}/chat/completions"
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
        }
        if "max_tokens" in self.config.extra:
            payload["max_tokens"] = self.config.extra["max_tokens"]

        headers = {
            "authorization": f"Bearer {self.config.api_key}",
            "content-type": "application/json",
        }

        url = f"{self.config.base_url}/chat/completions"
        try:
            response = self.client.post(url, headers=headers, json=payload)
            self._raise_for_status(response)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Network or connection failed: {exc}") from exc

        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            return ChatResponse(text="")
        message = choices[0].get("message") or {}
        return ChatResponse(text=str(message.get("content") or ""))

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
            "tools": self._tools_payload(tools),
        }
        if "max_tokens" in self.config.extra:
            payload["max_tokens"] = self.config.extra["max_tokens"]

        headers = {
            "authorization": f"Bearer {self.config.api_key}",
            "content-type": "application/json",
            "accept": "text/event-stream",
        }

        url = f"{self.config.base_url}/chat/completions"
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

        tool_calls = parse_openai_tool_calls_stream(events)
        if tool_calls:
            yield StreamChunk(tool_calls=tool_calls)

    def _complete_chat_with_tools_stream(self, messages: list[Message], tools: list[dict[str, Any]]) -> ChatResponse:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": self._messages_payload(messages),
            "stream": True,
            "tools": self._tools_payload(tools),
        }
        if "max_tokens" in self.config.extra:
            payload["max_tokens"] = self.config.extra["max_tokens"]

        headers = {
            "authorization": f"Bearer {self.config.api_key}",
            "content-type": "application/json",
            "accept": "text/event-stream",
        }

        url = f"{self.config.base_url}/chat/completions"
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

        tool_calls = parse_openai_tool_calls_stream(events)
        if tool_calls:
            return ChatResponse(text="", tool_calls=tool_calls)
        return ChatResponse(text="".join(text_parts))

    def _tools_payload(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        for tool in tools:
            function = {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema") or tool.get("parameters") or {"type": "object", "properties": {}, "required": []},
            }
            payload.append({"type": "function", "function": function})
        return payload

    def _messages_payload(self, messages: list[Message]) -> list[dict[str, Any]]:
        payload = []
        for message in messages:
            role = message["role"]
            if role == "tool":
                payload.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(message.get("tool_id") or message.get("tool_name", "tool")),
                        "content": json.dumps(message.get("tool_result", {})),
                    }
                )
            elif "tool_calls" in message:
                payload.append(
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": str(tool_call.get("id") or tool_call.get("name", "tool")),
                                "type": "function",
                                "function": {
                                    "name": str(tool_call.get("name", "tool")),
                                    "arguments": json.dumps(tool_call.get("arguments", {})),
                                },
                            }
                            for tool_call in message.get("tool_calls", [])
                        ],
                    }
                )
            elif "tool_input" in message:
                payload.append(
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": str(message.get("tool_id") or message.get("tool_name", "tool")),
                                "type": "function",
                                "function": {
                                    "name": str(message.get("tool_name", "tool")),
                                    "arguments": json.dumps(message.get("tool_input", {})),
                                },
                            }
                        ],
                    }
                )
            else:
                payload.append({"role": role, "content": message.get("content", "")})
        return payload

    def _text_delta(self, event: dict[str, Any]) -> str:
        choices = event.get("choices") or []
        if not choices:
            return ""
        delta = choices[0].get("delta") or {}
        return str(delta.get("content") or "")

    def _raise_for_status(self, response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if response.status_code in {401, 403}:
                raise ProviderError("Authentication failed. Check your API key.") from exc
            raise ProviderError(f"Provider request failed with HTTP {response.status_code}.") from exc
