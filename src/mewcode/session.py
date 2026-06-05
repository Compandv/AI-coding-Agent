from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypedDict


Role = Literal["user", "assistant", "tool"]


class Message(TypedDict, total=False):
    role: Role
    content: str
    tool_id: str
    tool_name: str
    tool_input: dict[str, Any]
    tool_calls: list[dict[str, Any]]
    tool_result: dict[str, Any]


@dataclass
class ChatSession:
    messages: list[Message]

    def __init__(self) -> None:
        self.messages = []

    def add_user_message(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str) -> None:
        self.messages.append({"role": "assistant", "content": content})

    def add_tool_call(self, tool_name: str, tool_input: dict[str, Any], tool_id: str | None = None) -> None:
        message: Message = {"role": "assistant", "tool_name": tool_name, "tool_input": tool_input}
        if tool_id is not None:
            message["tool_id"] = tool_id
        self.messages.append(message)

    def add_tool_calls(self, tool_calls: list[dict[str, Any]]) -> None:
        self.messages.append({"role": "assistant", "tool_calls": tool_calls})

    def add_tool_result(self, tool_name: str, tool_result: dict[str, Any], tool_id: str | None = None) -> None:
        message: Message = {"role": "tool", "tool_name": tool_name, "tool_result": tool_result}
        if tool_id is not None:
            message["tool_id"] = tool_id
        self.messages.append(message)

    def snapshot(self) -> list[Message]:
        return [message.copy() for message in self.messages]
