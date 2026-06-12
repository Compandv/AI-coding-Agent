from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import random
import secrets
import time
from typing import Any, Callable, Literal, TypedDict


Role = Literal["user", "assistant", "tool"]
SessionObserver = Callable[[str, dict[str, Any]], None]


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
    session_id: str
    _observer: SessionObserver | None

    def __init__(self, session_id: str | None = None, messages: list[Message] | None = None) -> None:
        self.messages = []
        self.session_id = session_id or new_session_id()
        self._observer = None
        if messages:
            self.messages = [message.copy() for message in messages]

    def add_user_message(self, content: str) -> None:
        self._append_message({"role": "user", "content": content})

    def add_assistant_message(self, content: str) -> None:
        self._append_message({"role": "assistant", "content": content})

    def add_tool_call(self, tool_name: str, tool_input: dict[str, Any], tool_id: str | None = None) -> None:
        message: Message = {"role": "assistant", "tool_name": tool_name, "tool_input": tool_input}
        if tool_id is not None:
            message["tool_id"] = tool_id
        self._append_message(message)

    def add_tool_calls(self, tool_calls: list[dict[str, Any]]) -> None:
        self._append_message({"role": "assistant", "tool_calls": tool_calls})

    def add_tool_result(self, tool_name: str, tool_result: dict[str, Any], tool_id: str | None = None) -> None:
        message: Message = {"role": "tool", "tool_name": tool_name, "tool_result": tool_result}
        if tool_id is not None:
            message["tool_id"] = tool_id
        self._append_message(message)

    def replace_messages(self, messages: list[Message], reason: str = "replace") -> None:
        self.messages = [message.copy() for message in messages]
        self._notify("replace_messages", {"reason": reason, "messages": self.snapshot()})

    def set_observer(self, observer: SessionObserver | None) -> None:
        self._observer = observer

    def snapshot(self) -> list[Message]:
        return [message.copy() for message in self.messages]

    def _append_message(self, message: Message) -> None:
        self.messages.append(message)
        self._notify("append_message", {"message": message.copy()})

    def _notify(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._observer is None:
            return
        self._observer(event_type, payload)


def new_session_id() -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        suffix = secrets.token_hex(2)
    except Exception:
        suffix = random.Random(time.time()).randbytes(2).hex()
    return f"{timestamp}-{suffix}"
