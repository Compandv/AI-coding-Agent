from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from mewcode.session import Message


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str | None = None


@dataclass
class ChatResponse:
    text: str
    tool_call: ToolCall | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.tool_call is not None and not self.tool_calls:
            self.tool_calls = [self.tool_call]
        elif self.tool_calls and self.tool_call is None:
            self.tool_call = self.tool_calls[0]


@dataclass
class StreamChunk:
    """One increment of a streamed response: a text delta or a final tool call."""

    text: str = ""
    tool_call: ToolCall | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.tool_call is not None and not self.tool_calls:
            self.tool_calls = [self.tool_call]
        elif self.tool_calls and self.tool_call is None:
            self.tool_call = self.tool_calls[0]


class ChatProvider(ABC):
    @abstractmethod
    def stream_chat(self, messages: list[Message]) -> Iterator[str]:
        """Yield text deltas for a chat response."""

    @abstractmethod
    def complete_chat(self, messages: list[Message], tools: list[dict[str, Any]] | None = None) -> ChatResponse:
        """Return either a final text response or a single tool call."""

    def stream_response(
        self, messages: list[Message], tools: list[dict[str, Any]] | None = None
    ) -> Iterator[StreamChunk]:
        """Yield text deltas as they arrive, then a tool call if one was requested.

        Default implementation falls back to the non-streaming ``complete_chat`` so
        providers without native streaming still work. Real providers override this.
        """
        response = self.complete_chat(messages, tools=tools)
        if response.tool_calls:
            yield StreamChunk(tool_calls=response.tool_calls)
        elif response.text:
            yield StreamChunk(text=response.text)
