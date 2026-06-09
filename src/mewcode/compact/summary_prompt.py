from __future__ import annotations

import json
import logging
import re

from mewcode.session import Message

LOGGER = logging.getLogger(__name__)

SUMMARY_INSTRUCTION = """You are MewCode's context compaction worker.
Summarize a coding-agent conversation only. Do not call tools.

Write in two phases:

<analysis>
Briefly reason about what must be preserved. This block will be discarded.
</analysis>

<summary>
## 1. Current Task Goal
## 2. User Messages And Hard Requirements
## 3. Completed Actions
## 4. Files Read
## 5. Files Written Or Edited
## 6. Commands And Tool Results
## 7. Errors Fixes And Decisions
## 8. Remaining Work
## 9. Constraints Modes Stored Paths And Precision Boundaries
</summary>

The formal summary must preserve user requirements accurately. Do not invent exact source code,
paths, command output, or file content. If exact details are needed, say they must be read again.
"""


def build_summary_prompt(
    messages: list[Message],
    recent_messages: list[Message] | None = None,
    *,
    focus: str = "",
    purpose: str = "final",
) -> str:
    prompt = [SUMMARY_INSTRUCTION.rstrip()]
    if purpose == "chunk":
        prompt.append("This is one chunk of a longer conversation. Preserve facts from this chunk for a later merge.")
    if focus.strip():
        prompt.extend(["", "[user supplied compact focus]", focus.strip()])
    prompt.extend(["", "[conversation]", serialize_conversation(messages)])
    if recent_messages is not None:
        prompt.extend(["", "[recent messages kept verbatim]", serialize_conversation(recent_messages)])
    return "\n".join(prompt)


def serialize_conversation(messages: list[Message]) -> str:
    lines: list[str] = []
    for index, message in enumerate(messages, start=1):
        role = str(message.get("role") or "unknown")
        if role == "assistant" and message.get("tool_calls"):
            calls = []
            for raw_call in message.get("tool_calls") or []:
                if not isinstance(raw_call, dict):
                    continue
                calls.append(
                    {
                        "id": raw_call.get("id"),
                        "name": raw_call.get("name"),
                        "arguments": raw_call.get("arguments"),
                    }
                )
            content = json.dumps(calls, ensure_ascii=False, sort_keys=True)
        elif role == "tool":
            payload = {
                "id": message.get("tool_id"),
                "name": message.get("tool_name"),
                "result": message.get("tool_result"),
            }
            content = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        else:
            content = str(message.get("content") or "")
        lines.append(f"{index}. {role}: {content}")
    return "\n".join(lines)


def extract_summary(text: str) -> str:
    summary_matches = re.findall(r"<summary>(.*?)</summary>", text, flags=re.DOTALL | re.IGNORECASE)
    if summary_matches:
        return summary_matches[-1].strip()
    final_matches = re.findall(r"<final_summary>(.*?)</final_summary>", text, flags=re.DOTALL | re.IGNORECASE)
    if final_matches:
        return final_matches[-1].strip()
    LOGGER.warning("summary tags not found")
    text = re.sub(r"<analysis>.*?</analysis>", "", text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()
