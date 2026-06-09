from __future__ import annotations

import json
import math
from typing import Any

from mewcode.session import Message

from .const import ESTIMATE_CHARS_PER_TOKEN


def _usage_value(usage: Any, name: str) -> int:
    value = getattr(usage, name, None)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def usage_anchor(usage: Any) -> int:
    return (
        _usage_value(usage, "input_tokens")
        + _usage_value(usage, "output_tokens")
        + _usage_value(usage, "cache_read_input_tokens")
        + _usage_value(usage, "cache_creation_input_tokens")
        + _usage_value(usage, "cache_read")
        + _usage_value(usage, "cache_write")
    )


def _value_chars(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        text = str(value)
    return len(text.encode("utf-8"))


def message_chars(messages: list[Message]) -> int:
    return sum(_value_chars(message) for message in messages)


def estimate_tokens(anchor: int, all_messages: list[Message], anchor_msg_len: int) -> int:
    start = max(0, min(anchor_msg_len, len(all_messages)))
    tail = all_messages[start:]
    return int(anchor) + math.ceil(message_chars(tail) / ESTIMATE_CHARS_PER_TOKEN)
