from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from mewcode.session import Message


@dataclass(frozen=True)
class PromptSection:
    name: str
    priority: int
    content: str

    def render(self) -> str:
        return f"## {self.name}\n{self.content.strip()}"


class IdentitySection(PromptSection):
    def __init__(self) -> None:
        super().__init__(
            name="Identity",
            priority=10,
            content=(
                "You are MewCode, a terminal AI coding assistant for software engineering work. "
                "You collaborate directly in the user's current workspace and help with code reading, "
                "planning, editing, debugging, and verification."
            ),
        )


class BehaviorSection(PromptSection):
    def __init__(self) -> None:
        super().__init__(
            name="Behavior",
            priority=20,
            content=(
                "Understand the user's goal, inspect relevant context before acting, and keep moving when the next "
                "step is clear. Ask concise clarification questions only when ambiguity would change architecture, "
                "scope, data model, safety, or user-facing behavior."
            ),
        )


class ToolUsageSection(PromptSection):
    def __init__(self) -> None:
        super().__init__(
            name="Tool Usage",
            priority=30,
            content=(
                "Prefer dedicated tools over shell commands for reading, searching, and editing workspace files. "
                "Use Glob or Grep to locate files, ReadFile to inspect files, EditFile for precise existing-file "
                "changes, WriteFile for new or full-file writes, and Bash only when command execution is necessary. "
                "If a user explicitly lists two or more files to read, request multiple ReadFile tool calls in the "
                "same model response so the Agent can execute them as one batch while still showing each file. Use "
                "ReadFile start_line/end_line for snippets or line ranges instead of Bash, python -c, cat, or type. "
                "After read tools, use metadata for file length, byte size, line count, returned range, and "
                "truncation status. Do not run Bash only to count or slice files already read. When using Bash on "
                "Windows, use Windows-compatible syntax; avoid POSIX heredocs (`<<EOF`) and Unix-only shell forms. "
                "Observe tool results before deciding the next step."
            ),
        )


class CodeQualitySection(PromptSection):
    def __init__(self) -> None:
        super().__init__(
            name="Code Quality",
            priority=40,
            content=(
                "Keep changes focused on the user's request. Follow the project's existing style and abstractions. "
                "Avoid unrelated refactors. Verify meaningful changes with targeted tests or commands when possible, "
                "and explain any verification that could not be run."
            ),
        )


class SecuritySection(PromptSection):
    def __init__(self) -> None:
        super().__init__(
            name="Security",
            priority=50,
            content=(
                "Do not expose secrets. Treat destructive filesystem operations, irreversible commands, credential "
                "changes, and network side effects with care. If a requested action is unsafe or outside the available "
                "tool boundaries, explain the limitation and choose a safer path."
            ),
        )


class TaskPatternSection(PromptSection):
    def __init__(self) -> None:
        super().__init__(
            name="Task Patterns",
            priority=60,
            content=(
                "For code explanation, inspect the relevant files and cite concrete paths. For bug fixing, reproduce "
                "or localize the issue before editing when practical. For implementation, make the smallest coherent "
                "change and verify it. For planning tasks, clarify broad requirements and produce an actionable plan "
                "without performing implementation work."
            ),
        )


class OutputStyleSection(PromptSection):
    def __init__(self) -> None:
        super().__init__(
            name="Output Style",
            priority=70,
            content=(
                "Reply in the user's language by default. Use concise Markdown. Put the most important result first, "
                "then mention changed files, verification, and remaining risks when relevant."
            ),
        )


@dataclass(frozen=True)
class CachePolicy:
    cache_system: bool = True
    cache_tools: bool = True


@dataclass(frozen=True)
class PromptPayload:
    system: str
    messages: list[Message]
    tools: list[dict[str, Any]]
    cache_policy: CachePolicy = field(default_factory=CachePolicy)
    metadata: dict[str, Any] = field(default_factory=dict)


def default_system_sections() -> list[PromptSection]:
    return [
        IdentitySection(),
        BehaviorSection(),
        ToolUsageSection(),
        CodeQualitySection(),
        SecuritySection(),
        TaskPatternSection(),
        OutputStyleSection(),
    ]


def assemble_system_prompt(sections: list[PromptSection] | None = None) -> str:
    ordered = sorted(sections or default_system_sections(), key=lambda section: (section.priority, section.name))
    return "\n\n".join(section.render() for section in ordered)


def system_reminder_message(content: str) -> Message:
    return {"role": "user", "content": f"<system-reminder>\n{content.strip()}\n</system-reminder>"}


PLAN_MODE_FULL_REMINDER = (
    "Full Plan Mode guidance: You are in MewCode Plan Mode. First clarify broad or ambiguous requests with "
    "AskUserQuestion. If several clarifications are already apparent, ask them in one AskUserQuestion call with a "
    "questions list. Use read-only tools to inspect the project. Do not write source files, edit source files, or run "
    "shell commands. By default, produce the plan in chat and do not create a plan file. Only use WritePlanFile when "
    "the user explicitly asks to save the plan as a file. When the plan is ready, summarize it and ask the user to "
    "accept it or request adjustments."
)

PLAN_MODE_BRIEF_REMINDER = (
    "Plan Mode is active. Stay read-only, clarify when needed, and produce plans in chat unless the user explicitly "
    "asks to save a plan file."
)


def plan_mode_reminder(model_request_index: int) -> Message:
    content = PLAN_MODE_FULL_REMINDER if model_request_index == 1 or model_request_index % 5 == 0 else PLAN_MODE_BRIEF_REMINDER
    return system_reminder_message(content)


def environment_context_message(root_dir: Path, now: datetime | None = None) -> Message:
    current_time = now or datetime.now().astimezone()
    lines = [
        "Environment context:",
        f"- Working directory: {root_dir.resolve()}",
        f"- Platform: {platform.system()} {platform.release()}",
        f"- Current time: {current_time.isoformat(timespec='seconds')}",
        f"- Git: {_git_summary(root_dir)}",
    ]
    return system_reminder_message("\n".join(lines))


def assemble_api_payload(
    *,
    session_messages: list[Message],
    tools: list[dict[str, Any]],
    root_dir: Path,
    mode: str = "normal",
    model_request_index: int = 0,
    sections: list[PromptSection] | None = None,
    cache_policy: CachePolicy | None = None,
    now: datetime | None = None,
) -> PromptPayload:
    messages = [environment_context_message(root_dir, now=now), *[message.copy() for message in session_messages]]
    metadata: dict[str, Any] = {"mode": mode, "model_request_index": model_request_index}
    if mode == "plan":
        reminder = plan_mode_reminder(model_request_index)
        messages.append(reminder)
        metadata["plan_reminder"] = "full" if "Full Plan Mode guidance" in reminder["content"] else "brief"

    return PromptPayload(
        system=assemble_system_prompt(sections),
        messages=messages,
        tools=[tool.copy() for tool in tools],
        cache_policy=cache_policy or CachePolicy(),
        metadata=metadata,
    )


def assembleAPIPayload(**kwargs: Any) -> PromptPayload:
    return assemble_api_payload(**kwargs)


def _git_summary(root_dir: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "status", "--short", "--branch"],
            cwd=root_dir,
            text=True,
            capture_output=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"
    if completed.returncode != 0:
        return "unavailable"
    output = completed.stdout.strip()
    if not output:
        return "clean working tree"
    first_line = output.splitlines()[0]
    dirty_count = max(0, len(output.splitlines()) - 1)
    return f"{first_line}; changed files: {dirty_count}"
