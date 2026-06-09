from __future__ import annotations

import math
from typing import Iterable

from mewcode.session import Message

from .const import PTL_DROP_PERCENTAGE, PTL_RETRY_LIMIT, RECENT_KEEP_MESSAGES, RECENT_KEEP_TOKENS
from .token import estimate_tokens


def pick_recent_tail(
    messages: list[Message],
    *,
    token_target: int = RECENT_KEEP_TOKENS,
    min_messages: int = RECENT_KEEP_MESSAGES,
) -> list[Message]:
    if not messages:
        return []
    recent: list[Message] = []
    for message in reversed(messages):
        recent.append(message.copy())
        recent_tokens = estimate_tokens(0, list(reversed(recent)), 0)
        if len(recent) >= min_messages and recent_tokens >= token_target:
            break
    recent.reverse()
    return _avoid_leading_tool_result(recent)


def _avoid_leading_tool_result(messages: list[Message]) -> list[Message]:
    while messages and messages[0].get("role") == "tool":
        messages = messages[1:]
    return messages


def group_by_user_turn(messages: list[Message]) -> list[list[Message]]:
    groups: list[list[Message]] = []
    current: list[Message] = []
    for message in messages:
        if message.get("role") == "user" and current:
            groups.append(current)
            current = [message.copy()]
        else:
            current.append(message.copy())
    if current:
        groups.append(current)
    return groups


def drop_groups_for_ptl(groups: list[list[Message]], retry_index: int) -> list[list[Message]]:
    if retry_index <= PTL_RETRY_LIMIT:
        drop_count = 1
    else:
        drop_count = max(1, math.ceil(len(groups) * PTL_DROP_PERCENTAGE))
    return groups[min(drop_count, len(groups)) :]


def flatten_groups(groups: Iterable[list[Message]]) -> list[Message]:
    flattened: list[Message] = []
    for group in groups:
        flattened.extend(message.copy() for message in group)
    return flattened
