from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, TextIO
import asyncio
import os
import signal
import sys
import threading
import time

from rich.console import Group
from rich.markdown import Markdown as RichMarkdown
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import Input, Static

from mewcode import __version__
from mewcode.agent import (
    AgentEvent,
    AgentError,
    AgentStatus,
    ClarificationQuestion,
    ConfirmationRequired,
    MemoryCommandResult,
    MemoryUpdated,
    PendingToolRequest,
    QuestionOption,
    SingleToolAgent,
    TextDelta,
    TurnCancelled,
    ToolFinished,
    ToolResultSpilled,
    ToolStarted,
    TurnComplete,
    UserQuestionRequested,
)
from mewcode.commands import CommandContext, CommandRegistry, CommandResult, make_builtin_registry
from mewcode.config import MewCodeConfig
from mewcode.context import (
    ContextChunkSummaryFinished,
    ContextChunkSummaryStarted,
    ContextCompressionFallbackUsed,
    ContextCompressionFailed,
    ContextCompressionFinished,
    ContextCompressionSkipped,
    ContextCompressionStarted,
    ContextEmergencyRetry,
    ContextStatsReported,
)
from mewcode.permissions import PERMISSION_MODES, PermissionMode
from mewcode.providers import ChatProvider, ProviderError, ToolCall
from mewcode.session import ChatSession


MEWCODE_LOGO = """███╗   ███╗
████╗ ████║
██╔████╔██║
██║╚██╔╝██║
██║ ╚═╝ ██║"""

FOOTER_HINT = (
    "esc interrupt · shift+tab permission · ctrl+c copy selection/last answer · "
    "ctrl+y last answer · ctrl+shift+y full transcript · ctrl+q quit"
)
LINE_MODE_HINT = "Line UI active. Set MEWCODE_UI=tui to force Textual. "
BRAILLE_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
ASCII_SPINNER_FRAMES = ["|", "/", "-", "\\"]
LINE_MODE_VALUES = {"line", "plain", "basic"}
TUI_MODE_VALUES = {"tui", "textual", "full"}
PHASE_STYLES = {
    "Thinking": "bold yellow",
    "Coding": "bold cyan",
    "Cultivating": "bold magenta",
    "Context": "bold blue",
    "Compacting": "bold blue",
    "Done": "bold green",
    "Error": "bold red",
    "Interrupted": "bold red",
}
TOOL_DONE_ICON = "\u2713"
TOOL_FAILED_ICON = "x"
PERMISSION_THEME_CLASSES = (
    "permission-mode-default",
    "permission-mode-edit",
    "permission-mode-plan",
    "permission-mode-bypass",
)


@dataclass
class DisplayMessage:
    role: str
    content: str
    active: bool = False


@dataclass
class ClarificationState:
    event: UserQuestionRequested
    question_index: int = 0
    selected_options: dict[str, int] = field(default_factory=dict)
    answers: dict[str, int] = field(default_factory=dict)
    custom_answers: dict[str, str] = field(default_factory=dict)

    @property
    def questions(self) -> list[ClarificationQuestion]:
        return self.event.questions

    def question_key(self, index: int) -> str:
        question = self.questions[index]
        return f"{index}:{question.id}"

    def is_answered(self, index: int) -> bool:
        return self.question_key(index) in self.answers

    def all_answered(self) -> bool:
        return bool(self.questions) and all(self.is_answered(index) for index in range(len(self.questions)))

    def selected_index(self, index: int) -> int:
        key = self.question_key(index)
        if key not in self.selected_options:
            self.selected_options[key] = default_question_option_index(self.questions[index])
        return self.selected_options[key]

    def set_selected_index(self, index: int, option_index: int) -> None:
        question = self.questions[index]
        if not question.options:
            return
        bounded = max(0, min(option_index, len(question.options) - 1))
        self.selected_options[self.question_key(index)] = bounded

    def confirm_current(self, custom_text: str = "") -> bool:
        if self.question_index >= len(self.questions):
            return False
        key = self.question_key(self.question_index)
        option = self.selected_option(self.question_index)
        if option is not None and option_allows_custom_input(option):
            value = custom_text.strip() or self.custom_answers.get(key, "").strip()
            if not value:
                return False
            self.custom_answers[key] = value
        else:
            self.custom_answers.pop(key, None)
        self.answers[key] = self.selected_index(self.question_index)
        return True

    def answer_for(self, index: int) -> QuestionOption | None:
        return self.selected_answer_option(index)

    def selected_option(self, index: int) -> QuestionOption | None:
        question = self.questions[index]
        if not question.options:
            return None
        option_index = self.selected_index(index)
        return question.options[max(0, min(option_index, len(question.options) - 1))]

    def selected_answer_option(self, index: int) -> QuestionOption | None:
        question = self.questions[index]
        if not question.options:
            return None
        option_index = self.answers.get(self.question_key(index))
        if option_index is None:
            return None
        return question.options[max(0, min(option_index, len(question.options) - 1))]

    def answer_label_for(self, index: int) -> str:
        option = self.selected_answer_option(index)
        if option is None:
            return "(missing)"
        custom_answer = self.custom_answers.get(self.question_key(index))
        if custom_answer and option_allows_custom_input(option):
            return custom_answer
        return option.label


@dataclass(frozen=True)
class PermissionChoice:
    label: str
    description: str
    action: str
    scope: str = "once"


@dataclass
class PermissionPromptState:
    pending: PendingToolRequest
    selected_index: int = 0

    @property
    def choices(self) -> list[PermissionChoice]:
        return [
            PermissionChoice("Yes", "Allow this tool call once.", "allow", "once"),
            PermissionChoice(
                "Yes, and don't ask again for this exact pattern.",
                "Write an exact allow rule to .mewcode/permissions.local.yaml.",
                "allow",
                "permanent",
            ),
            PermissionChoice("No", "Deny this tool call and let the model choose another path.", "deny", "once"),
        ]

    def move(self, delta: int) -> None:
        self.selected_index = max(0, min(self.selected_index + delta, len(self.choices) - 1))

    def selected_choice(self) -> PermissionChoice:
        return self.choices[self.selected_index]


class PromptInput(Input):
    _KEY_TEXT = {
        "slash": "/",
        "solidus": "/",
        "divide": "/",
        "numpad_divide": "/",
        "keypad_divide": "/",
    }

    def insert_key_text(self, text: str) -> None:
        selection = self.selection
        if selection.is_empty:
            self.insert_text_at_cursor(text)
        else:
            self.replace(text, *selection)

    def on_key(self, event) -> None:
        if event.key == "ctrl+c":
            self.app.action_copy_selection_or_last_answer()
            event.stop()
            event.prevent_default()
            return
        if event.key in {"shift+tab", "backtab"}:
            self.app.action_cycle_permission_mode()
            event.stop()
            event.prevent_default()
            return
        if event.key == "tab":
            complete = getattr(self.app, "action_complete_slash_command", None)
            if complete is not None:
                complete()
                event.stop()
                event.prevent_default()


def model_status_line(config: MewCodeConfig) -> str:
    return f"{config.model} with high effort {middle_dot()} API Usage Billing"


def agent_mode_label(mode: str) -> str:
    return "[PLAN]" if mode == "plan" else "[DEFAULT]"


def agent_mode_status_line(mode: str) -> str:
    return f"Mode: {agent_mode_label(mode)}"


def mcp_status_line(status: dict[str, int] | None) -> str:
    if not status:
        return ""
    configured = max(0, int(status.get("configured_servers", 0)))
    connected = max(0, int(status.get("connected_servers", 0)))
    tools = max(0, int(status.get("registered_tools", 0)))
    return f"MCP: {connected}/{configured} connected, {tools} tools"


def tool_result_updates_mcp_status(result: dict) -> bool:
    metadata = result.get("metadata") or {}
    return "activated_tools" in metadata or bool(metadata.get("activation_failed"))


def middle_dot() -> str:
    return chr(183)


def permission_mode_label(mode: str) -> str:
    labels = {
        "default": "Default",
        "acceptEdits": "Edit",
        "plan": "Plan",
        "bypassPermissions": "\u26a0 Bypass",
    }
    return labels.get(mode, mode)


def permission_mode_color(mode: str) -> str:
    colors = {
        "default": "#9ca3af",
        "acceptEdits": "#3b82f6",
        "plan": "#a855f7",
        "bypassPermissions": "#f97316",
    }
    return colors.get(mode, "#9ca3af")


def permission_theme_class(mode: str) -> str:
    classes = {
        "default": "permission-mode-default",
        "acceptEdits": "permission-mode-edit",
        "plan": "permission-mode-plan",
        "bypassPermissions": "permission-mode-bypass",
    }
    return classes.get(mode, "permission-mode-default")


def permission_status_line(mode: str) -> str:
    return f"Permission: {permission_mode_label(mode)}"


def permission_status_markup(mode: str) -> str:
    color = permission_mode_color(mode)
    label = escaped_text(permission_mode_label(mode))
    if mode == "bypassPermissions":
        return f"[bold {color}]Permission: {label}[/bold {color}]"
    return f"[{color}]Permission: {label}[/{color}]"


def escaped_text(content: str) -> str:
    return content.replace("[", r"\[")


def compact_text(content: str, limit: int = 120) -> str:
    compacted = " ".join(content.split())
    if len(compacted) <= limit:
        return compacted
    return f"{compacted[: limit - 3]}..."


def format_tool_elapsed(elapsed_seconds: float) -> str:
    return f"{max(0.0, elapsed_seconds):.1f}s"


def tool_argument(tool_call: ToolCall, name: str) -> str:
    value = tool_call.arguments.get(name)
    if value is None:
        return ""
    return compact_text(str(value))


def tool_action_label(tool_call: ToolCall) -> str:
    if tool_call.name == "ReadFile":
        target = tool_argument(tool_call, "path")
        return f"Read {target}" if target else "ReadFile"
    if tool_call.name == "WriteFile":
        target = tool_argument(tool_call, "path")
        return f"Write {target}" if target else "WriteFile"
    if tool_call.name == "EditFile":
        target = tool_argument(tool_call, "path")
        return f"Edit {target}" if target else "EditFile"
    if tool_call.name == "Glob":
        target = tool_argument(tool_call, "pattern")
        return f"Glob: {target}" if target else "Glob"
    if tool_call.name == "Grep":
        target = tool_argument(tool_call, "query")
        return f"Grep: {target}" if target else "Grep"
    if tool_call.name == "Bash":
        target = tool_argument(tool_call, "command")
        return f"Bash: {target}" if target else "Bash"
    if tool_call.name == "AskUserQuestion":
        return "AskUserQuestion"
    if tool_call.name == "WritePlanFile":
        target = tool_argument(tool_call, "path")
        content = str(tool_call.arguments.get("content") or "")
        line_count = len(content.splitlines()) if content else 0
        if target and line_count:
            return f"Write plan {target} ({line_count} lines)"
        return f"Write plan {target}" if target else "WritePlanFile"
    return tool_call.name


def user_message_text(content: str) -> str:
    return f"[bold blue]>[/bold blue] {escaped_text(content)}"


def assistant_message_text(content: str) -> str:
    return f"[bold magenta]●[/bold magenta] {escaped_text(content)}"


def assistant_message_renderable(content: str) -> Group:
    return Group(Text("●", style="bold magenta"), RichMarkdown(content))


def status_message_text(icon: str, phase: str, elapsed_seconds: int) -> str:
    style = PHASE_STYLES.get(phase, "dim")
    return f"[{style}]{icon} {phase}... ({elapsed_seconds}s)[/{style}]"


def done_status_text(elapsed_seconds: int) -> str:
    style = PHASE_STYLES["Done"]
    return f"[{style}]* Done ({elapsed_seconds}s)[/{style}]"


def interrupted_status_text(elapsed_seconds: int) -> str:
    style = PHASE_STYLES["Interrupted"]
    sep = chr(183)
    return f"[{style}]* Done (interrupted {sep} {elapsed_seconds}s)[/{style}]"


def error_status_text(message: str) -> str:
    style = PHASE_STYLES["Error"]
    return f"[{style}]* Error: {escaped_text(message)}[/{style}]"


def confirmation_status_text(tool_name: str) -> str:
    return (
        f"[bold yellow]* Permission required for {escaped_text(tool_name)} "
        "(yes=allow once / always=allow permanently / no=deny once)[/bold yellow]"
    )


def confirmation_status_plain(tool_name: str) -> str:
    return f"* Permission required for {tool_name} (yes=allow once / always=allow permanently / no=deny once)"


def permission_prompt_status_text() -> str:
    return "[bold yellow]* Permission required - use up/down and enter, or type yes/always/no[/bold yellow]"


def tool_permission_target_text(tool_call: ToolCall) -> str:
    if tool_call.name in {"ReadFile", "WriteFile", "EditFile", "WritePlanFile"}:
        return str(tool_call.arguments.get("path") or "")
    if tool_call.name == "Bash":
        return str(tool_call.arguments.get("command") or "")
    if tool_call.name == "Glob":
        return str(tool_call.arguments.get("pattern") or "")
    if tool_call.name == "Grep":
        return str(tool_call.arguments.get("query") or "")
    return compact_text(str(tool_call.arguments))


def permission_prompt_panel_text(state: PermissionPromptState) -> str:
    tool_call = state.pending.tool_call
    lines = [
        f"[bold cyan]{escaped_text(tool_action_label(tool_call))}[/bold cyan]",
        "",
        f"[bold yellow]{escaped_text(tool_call.name)} command[/bold yellow]",
    ]
    target = tool_permission_target_text(tool_call)
    if target:
        lines.extend(["", f"[white]{escaped_text(target)}[/white]"])
    if state.pending.decision is not None and state.pending.decision.reason:
        lines.extend(["", f"[dim]{escaped_text(state.pending.decision.reason)}[/dim]"])
    lines.extend(["", "[bold white]Do you want to proceed?[/bold white]"])
    for index, choice in enumerate(state.choices, start=1):
        selected = index - 1 == state.selected_index
        cursor = ">" if selected else " "
        description = f" [dim]- {escaped_text(choice.description)}[/dim]" if choice.description else ""
        line = f"{cursor} {index}. {escaped_text(choice.label)}{description}"
        if selected:
            lines.append(f"[bold cyan]{line}[/bold cyan]")
        else:
            lines.append(f"[dim]{line}[/dim]")
    lines.extend(["", "[dim]up/down select - enter confirm[/dim]"])
    return "\n".join(lines)


def permission_mode_status_text(mode: str) -> str:
    color = permission_mode_color(mode)
    label = escaped_text(permission_mode_label(mode))
    return f"[bold {color}]* Permission mode: {label}[/bold {color}]"


def permission_mode_status_plain(mode: str) -> str:
    return f"* Permission mode: {mode}"


def permission_options_plain(current: str) -> str:
    options = ", ".join(PERMISSION_MODES)
    return f"Permission mode: {current}\nAvailable modes: {options}"


def next_permission_mode(mode: str) -> PermissionMode:
    current = mode if mode in PERMISSION_MODES else PERMISSION_MODES[0]
    index = PERMISSION_MODES.index(current)  # type: ignore[arg-type]
    return PERMISSION_MODES[(index + 1) % len(PERMISSION_MODES)]


def tool_running_text(tool_call: ToolCall, icon: str, elapsed_seconds: float) -> str:
    label = escaped_text(tool_action_label(tool_call))
    return f"[bold cyan]{icon} {label} ({format_tool_elapsed(elapsed_seconds)})[/bold cyan]"


def tool_result_text(tool_call: ToolCall, ok: bool, elapsed_seconds: float, detail: str | None = None) -> str:
    label = escaped_text(tool_action_label(tool_call))
    elapsed = format_tool_elapsed(elapsed_seconds)
    if ok:
        return f"[bold green]{TOOL_DONE_ICON} {label} ({elapsed})[/bold green]"
    if detail:
        return f"[bold red]{TOOL_FAILED_ICON} {label} failed ({elapsed}): {escaped_text(detail)}[/bold red]"
    return f"[bold red]{TOOL_FAILED_ICON} {label} failed ({elapsed})[/bold red]"


def tool_result_spilled_text(event: ToolResultSpilled) -> str:
    return f"[dim]* {tool_result_spilled_plain(event)}[/dim]"


def tool_result_spilled_plain(event: ToolResultSpilled) -> str:
    return f"spilled {event.count} tool result(s) to disk (~{event.freed_chars} chars freed)"


def supports_braille_spinner() -> bool:
    return False if sys.stdout.encoding is None else sys.stdout.encoding.lower().replace("-", "") == "utf8"


def spinner_frames() -> list[str]:
    return BRAILLE_SPINNER_FRAMES if supports_braille_spinner() else ASCII_SPINNER_FRAMES


def running_in_vscode_terminal() -> bool:
    return os.environ.get("TERM_PROGRAM", "").strip().lower() == "vscode" or bool(os.environ.get("VSCODE_PID"))


def should_use_line_mode_for_terminal() -> bool:
    mode = os.environ.get("MEWCODE_UI", "").strip().lower()
    if mode in LINE_MODE_VALUES:
        return True
    if mode in TUI_MODE_VALUES:
        return False
    return False


def copy_status_text(label: str) -> str:
    return f"[bold green]* Copied {label}[/bold green]"


def nothing_to_copy_text(label: str) -> str:
    return f"[bold yellow]* No {label} to copy[/bold yellow]"


def mode_status_text(mode: str) -> str:
    if mode == "plan":
        return "[bold yellow]* Plan Mode: read-only tools enabled. Use /do to execute changes.[/bold yellow]"
    return "[bold green]* Do Mode: tools can write files and run commands. Use /plan for read-only planning.[/bold green]"


def mode_status_plain(mode: str) -> str:
    if mode == "plan":
        return "* Plan Mode: read-only tools enabled. Use /do to execute changes."
    return "* Do Mode: tools can write files and run commands. Use /plan for read-only planning."


def accept_plan_status_text(plan_path: str | None) -> str:
    if not plan_path:
        return "[bold yellow]* No plan file to accept yet.[/bold yellow]"
    return (
        f"[bold green]* Accepted plan: {escaped_text(plan_path)}. "
        "Use /do to start implementation or /plan to adjust.[/bold green]"
    )


def accept_plan_status_plain(plan_path: str | None) -> str:
    if not plan_path:
        return "* No plan file to accept yet."
    return f"* Accepted plan: {plan_path}. Use /do to start implementation or /plan to adjust."


def waiting_for_answer_text() -> str:
    return "[bold yellow]* Waiting for your clarification. Reply with the answer to continue planning.[/bold yellow]"


def question_message_text(question: str, options: list[str]) -> str:
    if not options:
        return question
    choices = "\n".join(f"- {option}" for option in options)
    return f"{question}\n{choices}"


CUSTOM_OPTION_LABELS = {"other", "custom", "\u5176\u4ed6", "\u5176\u5b83", "\u81ea\u5b9a\u4e49"}


def option_allows_custom_input(option: QuestionOption) -> bool:
    if option.allow_custom_input:
        return True
    label = option.label.strip().casefold().strip(" .:;\uff1a\uff1b")
    return label in CUSTOM_OPTION_LABELS


def default_question_option_index(question: ClarificationQuestion) -> int:
    for index, option in enumerate(question.options):
        if option.recommended:
            return index
    return 0


def clarification_questions_text(questions: list[ClarificationQuestion]) -> str:
    lines: list[str] = []
    for question_index, question in enumerate(questions, start=1):
        lines.append(f"{question_index}. {question.title}: {question.question}")
        for option in question.options:
            markers = []
            if option.recommended:
                markers.append("recommended")
            if option_allows_custom_input(option):
                markers.append("custom")
            marker = f" [{', '.join(markers)}]" if markers else ""
            detail = f" - {option.description}" if option.description else ""
            lines.append(f"   - {option.label}{marker}{detail}")
    return "\n".join(lines)


def can_use_interactive_clarification(event: UserQuestionRequested) -> bool:
    return bool(event.questions) and all(question.options for question in event.questions)


def should_render_structured_clarification(event: UserQuestionRequested) -> bool:
    if not event.questions:
        return False
    if len(event.questions) != 1:
        return True
    question = event.questions[0]
    legacy_options = [str(option) for option in event.options]
    question_options = [option.label for option in question.options]
    has_option_metadata = any(
        option.description or option.recommended or option.allow_custom_input for option in question.options
    )
    return not (
        event.question
        and question.id == "question_1"
        and question.title == "Question 1"
        and question.question == event.question
        and question_options == legacy_options
        and not has_option_metadata
    )


def clarification_submit_text(state: ClarificationState) -> str:
    lines = ["Clarification answers:"]
    for index, question in enumerate(state.questions):
        answer = state.answer_for(index)
        if answer is None:
            continue
        if option_allows_custom_input(answer) and state.custom_answers.get(state.question_key(index)):
            lines.append(f"- {question.title}: {state.answer_label_for(index)}")
            continue
        detail = f" - {answer.description}" if answer.description else ""
        lines.append(f"- {question.title}: {state.answer_label_for(index)}{detail}")
    return "\n".join(lines)


def clarification_panel_text(state: ClarificationState) -> str:
    question_count = len(state.questions)
    on_submit = state.question_index >= question_count
    tab_parts: list[str] = []
    for index, question in enumerate(state.questions):
        answered = state.is_answered(index)
        suffix = "\u2713" if answered else "\u25a1"
        label = f"{question.title} {suffix}"
        if index == state.question_index:
            tab_parts.append(f"[reverse bold magenta] {escaped_text(label)} [/reverse bold magenta]")
        elif answered:
            tab_parts.append(f"[bold green]{escaped_text(label)}[/bold green]")
        else:
            tab_parts.append(f"[dim]{escaped_text(label)}[/dim]")

    submit_suffix = "\u2713" if state.all_answered() else "\u25a1"
    submit_label = f"Submit {submit_suffix}"
    if on_submit:
        tab_parts.append(f"[reverse bold green] {submit_label} [/reverse bold green]")
    elif state.all_answered():
        tab_parts.append(f"[bold green]{submit_label}[/bold green]")
    else:
        tab_parts.append(f"[dim]{submit_label}[/dim]")

    lines = [" ".join(tab_parts), ""]
    if on_submit:
        lines.append("[bold green]Ready to submit clarification answers.[/bold green]")
        lines.append("")
        for index, question in enumerate(state.questions):
            label = state.answer_label_for(index)
            lines.append(f"[bold cyan]{escaped_text(question.title)}[/bold cyan]: {escaped_text(label)}")
        lines.append("")
        lines.append("[dim]left/right navigate questions - enter submit[/dim]")
        return "\n".join(lines)

    question = state.questions[state.question_index]
    question_key = state.question_key(state.question_index)
    lines.append(f"[bold magenta]{escaped_text(question.question)}[/bold magenta]")
    lines.append("")
    selected_index = state.selected_index(state.question_index)
    answered_index = state.answers.get(question_key)
    for index, option in enumerate(question.options):
        cursor = ">" if index == selected_index else " "
        confirmed = "*" if answered_index == index else " "
        recommended = " [bold green]\u63a8\u8350[/bold green]" if option.recommended else ""
        custom = " [bold cyan]custom[/bold cyan]" if option_allows_custom_input(option) else ""
        label = escaped_text(option.label)
        description = f" [dim]- {escaped_text(option.description)}[/dim]" if option.description else ""
        if index == selected_index:
            lines.append(f"[bold white]{cursor} {confirmed} {label}[/bold white]{recommended}{custom}{description}")
        else:
            lines.append(f"[dim]{cursor} {confirmed} {label}[/dim]{recommended}{custom}{description}")

    selected_option = state.selected_option(state.question_index)
    if selected_option is not None and option_allows_custom_input(selected_option):
        lines.append("")
        custom_answer = state.custom_answers.get(question_key, "")
        if custom_answer:
            lines.append(f"[dim]custom answer: {escaped_text(custom_answer)}[/dim]")
        lines.append("[dim]type a custom answer in the input box, then press enter[/dim]")

    lines.append("")
    lines.append("[dim]left/right navigate questions - up/down select - enter confirm[/dim]")
    return "\n".join(lines)


def parse_mode_command(text: str) -> tuple[str | None, str]:
    stripped = text.strip()
    lowered = stripped.lower()
    for command, mode in (("/plan", "plan"), ("/do", "normal")):
        if lowered == command:
            return mode, ""
        if lowered.startswith(f"{command} "):
            return mode, stripped[len(command) :].strip()
    return None, text


def is_accept_command(text: str) -> bool:
    return text.strip().lower() == "/accept"


def is_compact_command(text: str) -> bool:
    return text.strip().lower() == "/compact"


def compact_command_focus(text: str) -> str | None:
    stripped = text.strip()
    lowered = stripped.lower()
    if lowered == "/compact":
        return ""
    prefix = "/compact focus"
    if lowered.startswith(f"{prefix} "):
        return stripped[len(prefix) :].strip()
    return None


def is_context_command(text: str) -> bool:
    return text.strip().lower() == "/context"


def is_memory_command(text: str) -> bool:
    lowered = text.strip().lower()
    return lowered == "/memory" or lowered.startswith("/memory ")


def is_session_command(text: str) -> bool:
    lowered = text.strip().lower()
    return lowered == "/session" or lowered.startswith("/session ")


def copy_command_target(text: str) -> str | None:
    lowered = text.strip().lower()
    if lowered in {"/copy", "/copy transcript"}:
        return "transcript"
    if lowered in {"/copy last", "/copy answer", "/copy last-answer"}:
        return "last"
    return None


def context_event_text(event) -> str:
    if isinstance(event, ContextCompressionStarted):
        return f"[bold blue]* Compacting context ({event.kind}, before {event.before_tokens} tokens)[/bold blue]"
    if isinstance(event, ContextChunkSummaryStarted):
        return (
            f"[bold blue]* Summarizing context chunk {event.chunk_index}/{event.chunk_count} "
            f"({event.input_tokens} tokens)[/bold blue]"
        )
    if isinstance(event, ContextChunkSummaryFinished):
        return (
            f"[dim]* Context chunk {event.chunk_index}/{event.chunk_count} summarized "
            f"({event.output_tokens} tokens)[/dim]"
        )
    if isinstance(event, ContextCompressionFallbackUsed):
        suffix = (
            f", failures: {event.consecutive_failures}"
            if event.kind == "auto" and event.consecutive_failures
            else ""
        )
        label = "Local fallback only" if event.quality == "local" else "LLM compact fallback"
        return f"[bold yellow]* {label} ({event.kind}{suffix}): {escaped_text(event.reason)}[/bold yellow]"
    if isinstance(event, ContextCompressionFinished):
        return f"[dim]* {context_compacted_plain(event)}[/dim]"
    if isinstance(event, ContextCompressionFailed):
        suffix = f", failures: {event.consecutive_failures}" if event.consecutive_failures else ""
        label, message, fallback = context_failure_parts(event)
        style = "bold yellow" if fallback else "bold red"
        return f"[{style}]* {label} ({event.kind}{suffix}): {escaped_text(message)}[/{style}]"
    if isinstance(event, ContextCompressionSkipped):
        return f"[bold yellow]* Context compact skipped ({event.kind}): {escaped_text(event.reason)}[/bold yellow]"
    if isinstance(event, ContextEmergencyRetry):
        return f"[bold yellow]* Prompt too long; compacted context and retrying once.[/bold yellow]"
    if isinstance(event, ContextStatsReported):
        return context_stats_text(event)
    return ""


def context_event_plain(event) -> str:
    if isinstance(event, ContextCompressionStarted):
        return f"* Compacting context ({event.kind}, before {event.before_tokens} tokens)"
    if isinstance(event, ContextChunkSummaryStarted):
        return (
            f"* Summarizing context chunk {event.chunk_index}/{event.chunk_count} "
            f"({event.input_tokens} tokens)"
        )
    if isinstance(event, ContextChunkSummaryFinished):
        return f"* Context chunk {event.chunk_index}/{event.chunk_count} summarized ({event.output_tokens} tokens)"
    if isinstance(event, ContextCompressionFallbackUsed):
        suffix = (
            f", failures: {event.consecutive_failures}"
            if event.kind == "auto" and event.consecutive_failures
            else ""
        )
        label = "Local fallback only" if event.quality == "local" else "LLM compact fallback"
        return f"* {label} ({event.kind}{suffix}): {event.reason}"
    if isinstance(event, ContextCompressionFinished):
        return f"* {context_compacted_plain(event)}"
    if isinstance(event, ContextCompressionFailed):
        suffix = f", failures: {event.consecutive_failures}" if event.consecutive_failures else ""
        label, message, _ = context_failure_parts(event)
        return f"* {label} ({event.kind}{suffix}): {message}"
    if isinstance(event, ContextCompressionSkipped):
        return f"* Context compact skipped ({event.kind}): {event.reason}"
    if isinstance(event, ContextEmergencyRetry):
        return "* Prompt too long; compacted context and retrying once."
    if isinstance(event, ContextStatsReported):
        return context_stats_plain(event)
    return ""


def context_compacted_plain(event: ContextCompressionFinished) -> str:
    quality = getattr(event, "summary_quality", "llm")
    if quality == "llm":
        label = "LLM compact succeeded"
    elif quality == "llm_failed":
        label = "LLM compact fallback"
    elif quality == "local":
        label = "Local fallback only"
    else:
        label = str(quality)
    return f"Compacted: {event.before_tokens} -> {event.after_tokens} estimated tokens ({label})"


def context_stats_plain(event: ContextStatsReported) -> str:
    lines = [
        "* Context stats",
        f"- estimated tokens: {event.estimated_tokens}/{event.context_window_tokens}",
        f"- system/prompt: {event.system_prompt_tokens}",
        f"- tools: {event.tools_tokens}",
        f"- user history: {event.user_history_tokens}",
        f"- assistant history: {event.assistant_history_tokens}",
        f"- tool results: {event.tool_result_tokens}",
        f"- compact summary: {event.compact_summary_tokens}",
        f"- recent raw messages: {event.recent_raw_tokens}",
        f"- auto compact threshold: {event.auto_threshold_tokens}",
        f"- auto compact disabled: {event.auto_compact_disabled}",
    ]
    if event.last_compaction_before_tokens or event.last_compaction_after_tokens:
        lines.append(
            f"- last compaction: {event.last_compaction_before_tokens} -> {event.last_compaction_after_tokens}"
        )
    return "\n".join(lines)


def context_stats_text(event: ContextStatsReported) -> str:
    escaped = "\n".join(escaped_text(line) for line in context_stats_plain(event).splitlines())
    return f"[bold blue]{escaped}[/bold blue]"


def context_failure_parts(event: ContextCompressionFailed) -> tuple[str, str, bool]:
    fallback_prefix = "LLM compact failed; using local fallback:"
    message = event.message.strip()
    if message.casefold().startswith(fallback_prefix.casefold()):
        return "LLM compact fallback", message[len(fallback_prefix) :].strip(), True
    return "Context compact failed", message, False


def context_running_text(event: ContextCompressionStarted, icon: str, elapsed_seconds: float) -> str:
    elapsed = format_tool_elapsed(elapsed_seconds)
    return f"[bold blue]{icon} Compacting context ({event.kind}, before {event.before_tokens} tokens) ({elapsed})[/bold blue]"


def transcript_text(messages: list[DisplayMessage]) -> str:
    lines: list[str] = []
    labels = {"user": "User", "assistant": "Assistant"}
    for message in messages:
        label = labels.get(message.role)
        if label is None or not message.content:
            continue
        lines.append(f"{label}: {message.content}")
    return "\n\n".join(lines)


def last_assistant_text(messages: list[DisplayMessage]) -> str:
    for message in reversed(messages):
        if message.role == "assistant" and message.content:
            return message.content
    return ""


def set_system_clipboard_text(text: str) -> bool:
    if sys.platform == "win32":
        return _set_windows_clipboard_text(text)
    return False


def _set_windows_clipboard_text(text: str) -> bool:
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return False

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL

    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL

    cf_unicode_text = 13
    gmem_moveable = 0x0002
    data = (text + "\0").encode("utf-16-le")
    handle = kernel32.GlobalAlloc(gmem_moveable, len(data))
    if not handle:
        return False

    locked = kernel32.GlobalLock(handle)
    if not locked:
        kernel32.GlobalFree(handle)
        return False
    ctypes.memmove(locked, data, len(data))
    kernel32.GlobalUnlock(handle)

    if not user32.OpenClipboard(None):
        kernel32.GlobalFree(handle)
        return False
    try:
        if not user32.EmptyClipboard():
            kernel32.GlobalFree(handle)
            return False
        if not user32.SetClipboardData(cf_unicode_text, handle):
            kernel32.GlobalFree(handle)
            return False
        handle = None
        return True
    finally:
        user32.CloseClipboard()


class ChatMessage(Static):
    def __init__(self, message: DisplayMessage, **kwargs) -> None:
        super().__init__(**kwargs)
        self.message = message
        self.add_class(message.role)
        if message.active:
            self.add_class("active-user")

    def on_mount(self) -> None:
        self.refresh_message()

    def refresh_message(self) -> None:
        self.remove_class("active-user")
        if self.message.active:
            self.add_class("active-user")
        if self.message.role == "user":
            self.update(user_message_text(self.message.content))
        elif self.message.role == "assistant":
            self.update(assistant_message_renderable(self.message.content))
        else:
            self.update(self.message.content)


class MewCodeApp(App[int]):
    CSS = """
    Screen { background: #000000; color: #eeeeee; }
    #root { height: 100%; background: #000000; }
    #top { height: 6; padding: 1 2 0 2; background: #000000; }
    #logo { width: 28; color: #ff3333; text-style: bold; }
    #meta { width: 1fr; content-align: right top; color: #f2f2f2; }
    #divider { height: 1; color: #555555; padding: 0 2; }
    #chat { height: 1fr; padding: 1 2; background: #000000; }
    ChatMessage { width: 100%; margin: 0 0 1 0; padding: 0 1; }
    ChatMessage.active-user { background: #2a2a2a; }
    #input-area { height: 3; padding: 0 2; background: #000000; }
    #prompt-input { background: #111111; color: #ffffff; border: solid #9ca3af; }
    #prompt-input.permission-mode-default { border: solid #9ca3af; }
    #prompt-input.permission-mode-edit { border: solid #3b82f6; }
    #prompt-input.permission-mode-plan { border: solid #a855f7; }
    #prompt-input.permission-mode-bypass { border: solid #f97316; }
    #bottom-help { height: 1; padding: 0 2; color: #8a8a8a; background: #000000; }
    """

    BINDINGS = [
        Binding("escape", "interrupt", "Interrupt"),
        Binding("ctrl+c", "copy_selection_or_last_answer", "Copy", priority=True),
        Binding("ctrl+q", "quit", "Quit"),
        Binding("shift+tab", "cycle_permission_mode", "Permission mode"),
        Binding("ctrl+y", "copy_last_answer", "Copy last answer"),
        Binding("ctrl+shift+y", "copy_transcript", "Copy transcript"),
    ]

    def __init__(
        self,
        provider: ChatProvider,
        config: MewCodeConfig,
        session: ChatSession | None = None,
        agent: SingleToolAgent | None = None,
        cwd: Path | None = None,
        version: str = __version__,
        mcp_status_provider: Callable[[], dict[str, int]] | None = None,
    ) -> None:
        super().__init__()
        self.provider = provider
        self.config = config
        self.session = session or ChatSession()
        self.agent = agent
        self.cwd = cwd or Path.cwd()
        self.version = version
        self.mcp_status_provider = mcp_status_provider
        self.command_registry: CommandRegistry = make_builtin_registry()
        self.messages: list[DisplayMessage] = []
        self.status_started_at: float | None = None
        self.spinner_index = 0
        self.spinner_frames = spinner_frames()
        self.is_generating = False
        self.pending_request: PendingToolRequest | None = None
        self._phase: str | None = None
        self._interrupted = False
        self._status_widget: ChatMessage | None = None
        self._reply_widget: ChatMessage | None = None
        self._user_widget: ChatMessage | None = None
        self._tool_widgets: dict[str, ChatMessage] = {}
        self._tool_calls: dict[str, ToolCall] = {}
        self._tool_started_at: dict[str, float] = {}
        self._context_widget: ChatMessage | None = None
        self._context_event: ContextCompressionStarted | None = None
        self._context_started_at: float | None = None
        self.mode = "normal"
        self.permission_mode = config.permission_mode
        self.last_plan_path: str | None = None
        self._clarification_state: ClarificationState | None = None
        self._clarification_widget: ChatMessage | None = None
        self._permission_prompt_state: PermissionPromptState | None = None
        self._permission_prompt_widget: ChatMessage | None = None
        self._last_selection_text = ""
        self._previous_sigint_handler = None
        self._sigint_copy_handler_installed = False

    @property
    def title_line(self) -> str:
        return f"MewCode Agent v{self.version}"

    @property
    def model_line(self) -> str:
        parts = [model_status_line(self.config), agent_mode_status_line(self.mode), permission_status_line(self.permission_mode)]
        mcp_line = self.mcp_status_line
        if mcp_line:
            parts.append(mcp_line)
        return f" {middle_dot()} ".join(parts)

    @property
    def model_line_markup(self) -> str:
        parts = [
            escaped_text(model_status_line(self.config)),
            f"[bold #a855f7]{escaped_text(agent_mode_status_line(self.mode))}[/bold #a855f7]",
            permission_status_markup(self.permission_mode),
        ]
        mcp_line = self.mcp_status_line
        if mcp_line:
            parts.append(f"[#22d3ee]{escaped_text(mcp_line)}[/#22d3ee]")
        return f" {middle_dot()} ".join(parts)

    @property
    def mcp_status_line(self) -> str:
        if self.mcp_status_provider is None:
            return ""
        return mcp_status_line(self.mcp_status_provider())

    @property
    def header_markup(self) -> str:
        return f"{escaped_text(self.title_line)}\n{self.model_line_markup}"

    def compose(self) -> ComposeResult:
        with Vertical(id="root"):
            with Horizontal(id="top"):
                yield Static(MEWCODE_LOGO, id="logo")
                yield Static(self.header_markup, id="meta")
            yield Static("─" * 120, id="divider")
            yield VerticalScroll(id="chat")
            with Container(id="input-area"):
                yield PromptInput(placeholder="Type a message...", id="prompt-input")
            yield Static(FOOTER_HINT, id="bottom-help")

    def on_mount(self) -> None:
        self._append_message(DisplayMessage("status", "Ready."))
        self._apply_permission_theme()
        self._install_sigint_copy_handler()
        self.set_interval(0.1, self._tick_spinner)
        self.set_interval(0.2, self._remember_terminal_selection)
        self.call_after_refresh(self._focus_input)

    def on_unmount(self) -> None:
        self._restore_sigint_copy_handler()

    def action_cycle_permission_mode(self) -> None:
        self._set_permission_mode(next_permission_mode(self.permission_mode))
        self._append_status_notice(permission_mode_status_text(self.permission_mode))
        self.call_after_refresh(self._focus_input)

    def action_complete_slash_command(self) -> None:
        prompt = self.query_one("#prompt-input", PromptInput)
        candidates = self.command_registry.complete(prompt.value)
        if len(candidates) == 1:
            prompt.value = candidates[0]
            prompt.cursor_position = len(prompt.value)
            self.call_after_refresh(self._focus_input)
            return
        if candidates:
            self._append_status_notice(f"[dim]* Command matches: {escaped_text(', '.join(candidates))}[/dim]")
            self.call_after_refresh(self._focus_input)

    def _set_permission_mode(self, mode: PermissionMode) -> None:
        self.permission_mode = mode
        checker = getattr(self.agent, "permission_checker", None)
        if checker is not None:
            checker.set_mode(self.permission_mode)
        self._apply_permission_theme()

    def _apply_permission_theme(self) -> None:
        self._refresh_header()
        prompt = self.query_one("#prompt-input", PromptInput)
        prompt.remove_class(*PERMISSION_THEME_CLASSES)
        prompt.add_class(permission_theme_class(self.permission_mode))

    def _refresh_header(self) -> None:
        self.query_one("#meta", Static).update(self.header_markup)

    def copy_to_clipboard(self, text: str) -> None:
        if sys.platform == "win32":
            self._clipboard = text
            set_system_clipboard_text(text)
            return
        super().copy_to_clipboard(text)

    def _tick_spinner(self) -> None:
        if not self.is_generating and self._clarification_state is None:
            return
        if (self._status_widget is None or self._phase is None) and not self._tool_widgets and self._context_widget is None:
            return
        self.spinner_index = (self.spinner_index + 1) % len(self.spinner_frames)
        icon = self.spinner_frames[self.spinner_index]
        if self._status_widget is not None and self._phase is not None:
            self._status_widget.message.content = status_message_text(icon, self._phase, self._elapsed_seconds())
            self._status_widget.refresh_message()
        for key, widget in list(self._tool_widgets.items()):
            tool_call = self._tool_calls.get(key)
            if tool_call is None:
                continue
            widget.message.content = tool_running_text(tool_call, icon, self._tool_elapsed_seconds(key))
            widget.refresh_message()
        if self._context_widget is not None and self._context_event is not None:
            self._context_widget.message.content = context_running_text(
                self._context_event,
                icon,
                self._context_elapsed_seconds(),
            )
            self._context_widget.refresh_message()

    def on_key(self, event) -> None:
        if self._handle_permission_prompt_key(event):
            return
        if self._handle_clarification_key(event):
            return
        if isinstance(self.focused, PromptInput):
            text = PromptInput._KEY_TEXT.get(event.key)
            if event.character is None and text is not None:
                self.focused.insert_key_text(text)
                event.stop()
                event.prevent_default()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        if self._clarification_state is not None:
            custom_text = event.value
            if self._handle_clarification_enter(custom_text):
                event.input.value = ""
            return
        text = event.value.strip()
        event.input.value = ""
        if not text:
            self.call_after_refresh(self._focus_input)
            return
        if text in {"/exit", "/quit"}:
            self.exit(0)
            return
        self.run_worker(self._handle_turn(text), exclusive=True, group="turn")

    async def _handle_turn(self, text: str) -> None:
        command_result = self._dispatch_slash_command(text)
        if command_result is not None:
            await self._handle_command_result(command_result, text)
            return

        if self.agent is None:
            self._append_message(DisplayMessage("user", text, active=True))
            self._append_message(DisplayMessage("assistant", "No agent configured."))
            self._begin_status(error_status_text("No agent configured"), phase=None)
            self.call_after_refresh(self._focus_input)
            return

        lowered = text.strip().lower()
        if self.pending_request is not None:
            pending = self.pending_request
            if lowered in {"y", "yes"}:
                await self._resolve_permission_prompt(pending, action="allow", scope="once")
            elif lowered in {"a", "always", "permanent", "forever"}:
                await self._resolve_permission_prompt(pending, action="allow", scope="permanent")
            elif lowered in {"n", "no"}:
                await self._resolve_permission_prompt(pending, action="deny", scope="once")
            else:
                self._append_message(DisplayMessage("assistant", "Please reply yes, always, or no."))
                self._begin_status(permission_prompt_status_text(), phase=None)
                self.call_after_refresh(self._focus_input)
            return

        self._append_message(DisplayMessage("user", text, active=True))
        self._user_widget = self._last_widget()
        await self._drive(lambda: self._agent_stream_turn(text), phase="Thinking")

    def _dispatch_slash_command(self, text: str) -> CommandResult | None:
        return self.command_registry.dispatch(
            text,
            CommandContext(mode=self.mode, permission_mode=self.permission_mode, registry=self.command_registry),
        )

    async def _handle_command_result(self, result: CommandResult, original_text: str) -> None:
        if result.action == "message":
            self._append_message(DisplayMessage("assistant", result.message))
            self.call_after_refresh(self._focus_input)
            return
        if result.action == "clear":
            self._clear_display()
            self._append_status_notice("[dim]* Screen cleared[/dim]")
            self.call_after_refresh(self._focus_input)
            return
        if result.action == "copy":
            if result.copy_target == "last":
                self.action_copy_last_answer()
            else:
                self.action_copy_transcript()
            self.call_after_refresh(self._focus_input)
            return
        if result.action == "accept":
            self.mode = "normal"
            self._refresh_header()
            self._append_status_notice(accept_plan_status_text(self.last_plan_path))
            self.call_after_refresh(self._focus_input)
            return
        if result.action == "set_mode":
            self.mode = result.mode or "normal"
            self._refresh_header()
            self._append_status_notice(mode_status_text(self.mode))
            if result.remainder:
                await self._send_agent_text(result.remainder)
            else:
                self.call_after_refresh(self._focus_input)
            return
        if result.action == "permission_status":
            self._append_message(DisplayMessage("assistant", permission_options_plain(self.permission_mode)))
            self.call_after_refresh(self._focus_input)
            return
        if result.action == "set_permission":
            if result.permission_mode is not None:
                self._set_permission_mode(result.permission_mode)
            self._append_status_notice(permission_mode_status_text(self.permission_mode))
            self.call_after_refresh(self._focus_input)
            return
        if result.action == "status":
            self._append_message(DisplayMessage("assistant", self._runtime_status_text()))
            self.call_after_refresh(self._focus_input)
            return
        if result.action == "compact":
            await self._drive(lambda: self._agent_stream_compact(result.focus), phase="Compacting")
            return
        if result.action == "context":
            await self._drive(self._agent_stream_context_stats, phase="Context")
            return
        if result.action == "memory":
            await self._drive(lambda: self._agent_stream_memory_command(result.command_line), phase="Context")
            return
        if result.action == "agent_prompt":
            await self._send_agent_text(result.prompt, display_text=original_text)
            return

    async def _send_agent_text(self, text: str, display_text: str | None = None) -> None:
        if self.agent is None:
            self._append_message(DisplayMessage("user", display_text or text, active=True))
            self._append_message(DisplayMessage("assistant", "No agent configured."))
            self._begin_status(error_status_text("No agent configured"), phase=None)
            self.call_after_refresh(self._focus_input)
            return
        self._append_message(DisplayMessage("user", display_text or text, active=True))
        self._user_widget = self._last_widget()
        await self._drive(lambda: self._agent_stream_turn(text), phase="Thinking")

    def _clear_display(self) -> None:
        self.messages.clear()
        self._status_widget = None
        self._reply_widget = None
        self._user_widget = None
        self._tool_widgets.clear()
        self._tool_calls.clear()
        self._tool_started_at.clear()
        self._context_widget = None
        chat = self.query_one("#chat", VerticalScroll)
        for widget in list(chat.query(ChatMessage)):
            widget.remove()

    def _runtime_status_text(self) -> str:
        lines = [
            "MewCode status",
            f"- model: {model_status_line(self.config)}",
            f"- cwd: {self.cwd}",
            f"- agent mode: {agent_mode_label(self.mode)}",
            f"- permission: {self.permission_mode}",
        ]
        mcp_line = self.mcp_status_line
        if mcp_line:
            lines.append(f"- mcp: {mcp_line}")
        context_manager = getattr(self.agent, "context_manager", None)
        if context_manager is not None:
            tokens = context_manager.estimate_session_tokens(self.session)
            window = context_manager.config.context_window_tokens
            lines.append(f"- context: {tokens}/{window} estimated session tokens")
        else:
            lines.append("- context: not configured")
        memory_manager = getattr(self.agent, "memory_manager", None)
        if memory_manager is not None:
            counts = memory_manager.status_counts()
            lines.append(
                "- memory: "
                f"{counts.get('memories', 0)} memories, {counts.get('sessions', 0)} sessions, "
                f"auto={'on' if counts.get('auto_memory_enabled') else 'off'}"
            )
        else:
            lines.append("- memory: not configured")
        return "\n".join(lines)

    def _agent_stream_turn(self, text: str) -> Iterator[AgentEvent]:
        if self.agent is None:
            return iter(())
        try:
            return self.agent.stream_turn(self.session, text, mode=self.mode)
        except TypeError:
            return self.agent.stream_turn(self.session, text)

    def _agent_stream_compact(self, focus: str = "") -> Iterator[AgentEvent]:
        if self.agent is None:
            return iter(())
        compact = getattr(self.agent, "stream_compact", None)
        if compact is None:
            return iter(())
        try:
            return compact(self.session, focus=focus)
        except TypeError:
            return compact(self.session)

    def _agent_stream_context_stats(self) -> Iterator[AgentEvent]:
        if self.agent is None:
            return iter(())
        stats = getattr(self.agent, "stream_context_stats", None)
        if stats is None:
            return iter(())
        try:
            return stats(self.session, mode=self.mode)
        except TypeError:
            return stats(self.session)

    def _agent_stream_memory_command(self, text: str) -> Iterator[AgentEvent]:
        if self.agent is None:
            return iter(())
        command = getattr(self.agent, "stream_memory_command", None)
        if command is None:
            return iter(())
        return command(self.session, text)

    async def _drive(self, make_stream: Callable[[], Iterator[AgentEvent]], phase: str) -> None:
        self.is_generating = True
        self._interrupted = False
        self.status_started_at = time.monotonic()
        self._reply_widget = None
        self._tool_widgets = {}
        self._tool_calls = {}
        self._tool_started_at = {}
        self._context_widget = None
        self._context_event = None
        self._context_started_at = None
        self._clarification_state = None
        self._clarification_widget = None
        if self._permission_prompt_state is None:
            self._permission_prompt_widget = None
        self._begin_status(status_message_text(self.spinner_frames[self.spinner_index], phase, 0), phase=phase)
        try:
            await asyncio.to_thread(self._consume_stream, make_stream)
        except ProviderError as exc:
            self._on_error(str(exc))
        self.is_generating = False
        self._phase = "Cultivating" if self._clarification_state is not None else None
        if self._user_widget is not None:
            self._user_widget.message.active = False
            self._user_widget.refresh_message()
            self._user_widget = None
        self.call_after_refresh(self._focus_input)

    def _consume_stream(self, make_stream: Callable[[], Iterator[AgentEvent]]) -> None:
        for event in make_stream():
            if self._interrupted:
                break
            self.call_from_thread(self._on_event, event)

    def _on_event(self, event: AgentEvent) -> None:
        if isinstance(event, TextDelta):
            self._phase = "Coding"
            if self._reply_widget is None:
                self._reply_widget = self._mount_before_status(DisplayMessage("assistant", ""))
            self._reply_widget.message.content += event.text
            self._reply_widget.refresh_message()
            self._scroll_chat_end()
        elif isinstance(event, AgentStatus):
            self._phase = event.phase
        elif isinstance(event, ContextCompressionStarted):
            self._phase = "Compacting"
            self._begin_context_status(event)
        elif isinstance(event, ContextChunkSummaryStarted):
            text = context_event_text(event)
            if text:
                self._mount_before_status(DisplayMessage("status", text))
        elif isinstance(event, ContextChunkSummaryFinished):
            text = context_event_text(event)
            if text:
                self._mount_before_status(DisplayMessage("status", text))
        elif isinstance(event, ContextCompressionFallbackUsed):
            text = context_event_text(event)
            if text:
                self._mount_before_status(DisplayMessage("status", text))
        elif isinstance(event, ContextCompressionFinished):
            self._finish_context_status(context_event_text(event))
        elif isinstance(event, ContextCompressionFailed):
            text = context_event_text(event)
            if text:
                _, _, fallback = context_failure_parts(event)
                if fallback:
                    self._finish_context_status(text)
                else:
                    self._mount_before_status(DisplayMessage("status", text))
        elif isinstance(event, ContextCompressionSkipped):
            self._finish_context_status(context_event_text(event))
        elif isinstance(event, ContextEmergencyRetry):
            text = context_event_text(event)
            if text:
                self._mount_before_status(DisplayMessage("status", text))
        elif isinstance(event, ContextStatsReported):
            text = context_event_text(event)
            if text:
                self._mount_before_status(DisplayMessage("status", text))
        elif isinstance(event, MemoryCommandResult):
            self._mount_before_status(DisplayMessage("assistant", event.content))
        elif isinstance(event, MemoryUpdated):
            self._mount_before_status(DisplayMessage("status", f"[dim]* Memory updated ({event.count} item(s))[/dim]"))
        elif isinstance(event, ToolStarted):
            self._phase = "Coding"
            self._begin_tool_status(event.tool_call)
        elif isinstance(event, ToolFinished):
            ok = bool(event.result.get("ok"))
            self._remember_plan_file(event.result)
            detail = None if ok else str(event.result.get("error") or event.result.get("content") or "")
            self._finish_tool_status(event.tool_call, ok, detail)
            if tool_result_updates_mcp_status(event.result):
                self._refresh_header()
            self._reply_widget = None
        elif isinstance(event, ToolResultSpilled):
            self._mount_before_status(DisplayMessage("status", tool_result_spilled_text(event)))
        elif isinstance(event, ConfirmationRequired):
            self._begin_permission_prompt(event.pending_request)
        elif isinstance(event, UserQuestionRequested):
            if can_use_interactive_clarification(event):
                self._begin_clarification(event)
            else:
                self._reply_widget = self._mount_before_status(
                    DisplayMessage("assistant", question_message_text(event.question, event.options))
                )
                self._finish_status(waiting_for_answer_text())
        elif isinstance(event, TurnComplete):
            if event.reason == "await_user":
                return
            self._finish_status(done_status_text(self._elapsed_seconds()))
        elif isinstance(event, TurnCancelled):
            self._finish_running_tool(False, event.reason)
            self._finish_status(interrupted_status_text(self._elapsed_seconds()))
        elif isinstance(event, AgentError):
            self._on_error(event.message)

    def _on_error(self, message: str) -> None:
        self._interrupted = True
        self._clarification_state = None
        self._clarification_widget = None
        self._permission_prompt_state = None
        self._permission_prompt_widget = None
        self._finish_running_tool(False, message)
        self._finish_status(error_status_text(message))

    def _begin_clarification(self, event: UserQuestionRequested) -> None:
        state = ClarificationState(event=event)
        self._clarification_state = state
        self._phase = "Cultivating"
        self._reply_widget = self._mount_before_status(DisplayMessage("status", clarification_panel_text(state)))
        self._clarification_widget = self._reply_widget
        if self._status_widget is not None:
            self._status_widget.message.content = status_message_text(
                self.spinner_frames[self.spinner_index], "Cultivating", self._elapsed_seconds()
            )
            self._status_widget.refresh_message()
        self.call_after_refresh(self._focus_input)

    def _begin_permission_prompt(self, pending: PendingToolRequest) -> None:
        self.pending_request = pending
        state = PermissionPromptState(pending=pending)
        self._permission_prompt_state = state
        self._permission_prompt_widget = self._mount_before_status(
            DisplayMessage("status", permission_prompt_panel_text(state))
        )
        self._finish_status(permission_prompt_status_text())
        self.call_after_refresh(self._focus_input)

    def _refresh_permission_prompt(self) -> None:
        if self._permission_prompt_state is None or self._permission_prompt_widget is None:
            return
        self._permission_prompt_widget.message.content = permission_prompt_panel_text(self._permission_prompt_state)
        self._permission_prompt_widget.refresh_message()
        self.call_after_refresh(self._scroll_chat_end)

    def _handle_permission_prompt_key(self, event) -> bool:
        if self._permission_prompt_state is None:
            return False
        if event.key not in {"up", "down", "enter"}:
            return False
        event.stop()
        event.prevent_default()
        if event.key == "up":
            self._permission_prompt_state.move(-1)
            self._refresh_permission_prompt()
        elif event.key == "down":
            self._permission_prompt_state.move(1)
            self._refresh_permission_prompt()
        elif event.key == "enter":
            self.run_worker(self._submit_permission_prompt(), exclusive=True, group="turn")
        return True

    async def _submit_permission_prompt(self) -> None:
        state = self._permission_prompt_state
        if state is None:
            return
        choice = state.selected_choice()
        await self._resolve_permission_prompt(
            state.pending,
            action=choice.action,
            scope=choice.scope,
            choice=choice,
        )

    async def _resolve_permission_prompt(
        self,
        pending: PendingToolRequest,
        action: str,
        scope: str = "once",
        choice: PermissionChoice | None = None,
    ) -> None:
        if choice is None:
            choice = next(
                (
                    candidate
                    for candidate in PermissionPromptState(pending=pending).choices
                    if candidate.action == action and candidate.scope == scope
                ),
                None,
            )
        if self._permission_prompt_widget is not None and self._permission_prompt_widget.is_mounted:
            label = choice.label if choice is not None else action
            self._permission_prompt_widget.message.content = (
                f"[bold green]Permission choice:[/bold green] {escaped_text(label)}"
            )
            self._permission_prompt_widget.refresh_message()
        self.pending_request = None
        self._permission_prompt_state = None
        self._permission_prompt_widget = None
        if action == "deny":
            await self._drive(lambda: self.agent.stream_deny(self.session, pending), phase="Coding")
            return
        await self._drive(lambda: self.agent.stream_confirm(self.session, pending, scope=scope), phase="Coding")

    def _refresh_clarification(self) -> None:
        if self._clarification_state is None or self._clarification_widget is None:
            return
        self._clarification_widget.message.content = clarification_panel_text(self._clarification_state)
        self._clarification_widget.refresh_message()
        self.call_after_refresh(self._scroll_chat_end)

    def _handle_clarification_key(self, event) -> bool:
        if self._clarification_state is None:
            return False
        if event.key not in {"left", "right", "up", "down", "enter"}:
            return False
        event.stop()
        event.prevent_default()
        if event.key == "left":
            self._move_clarification_left()
        elif event.key == "right":
            self._move_clarification_right()
        elif event.key == "up":
            self._move_clarification_selection(-1)
        elif event.key == "down":
            self._move_clarification_selection(1)
        elif event.key == "enter":
            prompt = self.query_one("#prompt-input", Input)
            if self._handle_clarification_enter(prompt.value):
                prompt.value = ""
        return True

    def _move_clarification_left(self) -> None:
        state = self._clarification_state
        if state is None:
            return
        state.question_index = max(0, state.question_index - 1)
        self._refresh_clarification()

    def _move_clarification_right(self) -> None:
        state = self._clarification_state
        if state is None:
            return
        question_count = len(state.questions)
        if state.question_index >= question_count:
            return
        if not state.is_answered(state.question_index):
            self._refresh_clarification()
            return
        if state.question_index == question_count - 1:
            if state.all_answered():
                state.question_index = question_count
        else:
            state.question_index += 1
        self._refresh_clarification()

    def _move_clarification_selection(self, delta: int) -> None:
        state = self._clarification_state
        if state is None or state.question_index >= len(state.questions):
            return
        current = state.selected_index(state.question_index)
        state.set_selected_index(state.question_index, current + delta)
        self._refresh_clarification()

    def _handle_clarification_enter(self, custom_text: str = "") -> bool:
        state = self._clarification_state
        if state is None:
            return False
        question_count = len(state.questions)
        if state.question_index >= question_count:
            if state.all_answered():
                self.run_worker(self._submit_clarification(), exclusive=True, group="turn")
                return True
            return False
        if not state.confirm_current(custom_text):
            self._refresh_clarification()
            self.call_after_refresh(self._focus_input)
            return False
        if state.question_index == question_count - 1:
            if state.all_answered():
                state.question_index = question_count
        else:
            state.question_index += 1
        self._refresh_clarification()
        return True

    async def _submit_clarification(self) -> None:
        state = self._clarification_state
        if state is None or not state.all_answered():
            return
        answer_text = clarification_submit_text(state)
        if self._clarification_widget is not None and self._clarification_widget.is_mounted:
            self._clarification_widget.message.content = answer_text
            self._clarification_widget.refresh_message()
        self._clarification_state = None
        self._clarification_widget = None
        self._finish_status(done_status_text(self._elapsed_seconds()))
        self._append_message(DisplayMessage("user", answer_text, active=True))
        self._user_widget = self._last_widget()
        await self._drive(lambda: self._agent_stream_turn(answer_text), phase="Thinking")

    def action_interrupt(self) -> None:
        if self.is_generating:
            self._interrupted = True
            cancel = getattr(self.agent, "cancel", None)
            if cancel is not None:
                cancel()
            self._finish_running_tool(False, "interrupted")
            self._finish_status(interrupted_status_text(self._elapsed_seconds()))
        if self._clarification_state is not None:
            self._clarification_state = None
            self._clarification_widget = None
            self._finish_status(interrupted_status_text(self._elapsed_seconds()))
        if self._permission_prompt_state is not None:
            self.pending_request = None
            self._permission_prompt_state = None
            self._permission_prompt_widget = None
            self._finish_status(interrupted_status_text(self._elapsed_seconds()))
        self.call_after_refresh(self._focus_input)

    def action_copy_last_answer(self) -> None:
        self._copy_text(last_assistant_text(self.messages), "last answer")

    def action_copy_selection_or_last_answer(self) -> None:
        selection = self._current_selection_text()
        if selection:
            self._copy_text(selection, "selection")
            return
        if self._last_selection_text:
            self._copy_text(self._last_selection_text, "selection")
            return
        self._copy_text(last_assistant_text(self.messages), "last answer")

    def action_copy_transcript(self) -> None:
        self._copy_text(transcript_text(self.messages), "transcript")

    def _copy_text(self, text: str, label: str) -> None:
        if not text:
            self._append_status_notice(nothing_to_copy_text(label))
            return
        self.copy_to_clipboard(text)
        self._append_status_notice(copy_status_text(label))

    def _remember_terminal_selection(self) -> None:
        selection = self._current_selection_text()
        if selection:
            self._last_selection_text = selection

    def _current_selection_text(self) -> str:
        try:
            return self.screen.get_selected_text()
        except Exception:
            return ""

    def _install_sigint_copy_handler(self) -> None:
        try:
            self._previous_sigint_handler = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, self._handle_sigint_copy)
        except (OSError, ValueError):
            return
        self._sigint_copy_handler_installed = True

    def _restore_sigint_copy_handler(self) -> None:
        if not self._sigint_copy_handler_installed:
            return
        try:
            signal.signal(signal.SIGINT, self._previous_sigint_handler)
        except (OSError, ValueError, TypeError):
            pass
        self._sigint_copy_handler_installed = False

    def _handle_sigint_copy(self, signum, frame) -> None:
        try:
            self.call_from_thread(self.action_copy_selection_or_last_answer)
        except Exception:
            try:
                self.call_later(self.action_copy_selection_or_last_answer)
            except Exception:
                pass

    def _append_status_notice(self, text: str) -> None:
        if self._status_widget is not None and self._status_widget.is_mounted:
            self._mount_before_status(DisplayMessage("status", text))
        else:
            self._append_message(DisplayMessage("status", text))

    def _focus_input(self) -> None:
        self.query_one("#prompt-input", Input).focus()

    def _append_message(self, message: DisplayMessage) -> ChatMessage:
        self.messages.append(message)
        widget = ChatMessage(message)
        self.query_one("#chat", VerticalScroll).mount(widget)
        self.call_after_refresh(self._scroll_chat_end)
        return widget

    def _last_widget(self) -> ChatMessage:
        return list(self.query_one("#chat", VerticalScroll).query(ChatMessage))[-1]

    def _begin_status(self, text: str, phase: str | None) -> None:
        """Open a fresh status line pinned at the bottom of the current reply."""
        self._phase = phase
        message = DisplayMessage("status", text)
        self.messages.append(message)
        widget = ChatMessage(message)
        self.query_one("#chat", VerticalScroll).mount(widget)
        self._status_widget = widget
        self.call_after_refresh(self._scroll_chat_end)

    def _mount_before_status(self, message: DisplayMessage) -> ChatMessage:
        """Mount a widget directly above the pinned status line so status stays last."""
        self.messages.append(message)
        widget = ChatMessage(message)
        chat = self.query_one("#chat", VerticalScroll)
        if self._status_widget is not None and self._status_widget.is_mounted:
            chat.mount(widget, before=self._status_widget)
        else:
            chat.mount(widget)
        self.call_after_refresh(self._scroll_chat_end)
        return widget

    def _begin_tool_status(self, tool_call: ToolCall) -> None:
        key = self._tool_key(tool_call)
        self._tool_calls[key] = tool_call
        self._tool_started_at[key] = time.monotonic()
        self._tool_widgets[key] = self._mount_before_status(
            DisplayMessage("status", tool_running_text(tool_call, self.spinner_frames[self.spinner_index], 0.0))
        )

    def _finish_tool_status(self, tool_call: ToolCall, ok: bool, detail: str | None = None) -> None:
        key = self._tool_key(tool_call)
        text = tool_result_text(tool_call, ok, self._tool_elapsed_seconds(key), detail)
        widget = self._tool_widgets.get(key)
        if widget is not None and widget.is_mounted:
            widget.message.content = text
            widget.refresh_message()
        else:
            self._mount_before_status(DisplayMessage("status", text))
        self._tool_widgets.pop(key, None)
        self._tool_calls.pop(key, None)
        self._tool_started_at.pop(key, None)

    def _finish_running_tool(self, ok: bool, detail: str | None = None) -> None:
        for tool_call in list(self._tool_calls.values()):
            self._finish_tool_status(tool_call, ok, detail)
        if self._context_widget is not None:
            self._finish_context_status(interrupted_status_text(self._elapsed_seconds()))

    def _begin_context_status(self, event: ContextCompressionStarted) -> None:
        self._context_event = event
        self._context_started_at = time.monotonic()
        self._context_widget = self._mount_before_status(
            DisplayMessage(
                "status",
                context_running_text(event, self.spinner_frames[self.spinner_index], 0.0),
            )
        )

    def _finish_context_status(self, text: str) -> None:
        if not text:
            return
        widget = self._context_widget
        if widget is not None and widget.is_mounted:
            widget.message.content = text
            widget.refresh_message()
        else:
            self._mount_before_status(DisplayMessage("status", text))
        self._context_widget = None
        self._context_event = None
        self._context_started_at = None

    def _remember_plan_file(self, result: dict) -> None:
        metadata = result.get("metadata") or {}
        if not metadata.get("plan_file"):
            return
        path = metadata.get("relative_path") or metadata.get("path")
        if path:
            self.last_plan_path = str(path)

    def _finish_status(self, text: str) -> None:
        if self._status_widget is None:
            self._begin_status(text, phase=None)
            return
        self._phase = None
        self._status_widget.message.content = text
        self._status_widget.refresh_message()
        self._status_widget = None

    def _scroll_chat_end(self) -> None:
        self.query_one("#chat", VerticalScroll).scroll_end(animate=False)

    def _elapsed_seconds(self) -> int:
        if self.status_started_at is None:
            return 0
        return int(time.monotonic() - self.status_started_at)

    def _tool_key(self, tool_call: ToolCall) -> str:
        return tool_call.id or f"{tool_call.name}:{repr(sorted(tool_call.arguments.items()))}"

    def _tool_elapsed_seconds(self, key: str) -> float:
        started_at = self._tool_started_at.get(key)
        if started_at is None:
            return 0.0
        return time.monotonic() - started_at

    def _context_elapsed_seconds(self) -> float:
        if self._context_started_at is None:
            return 0.0
        return time.monotonic() - self._context_started_at


class MewCodeRepl:
    def __init__(
        self,
        provider: ChatProvider,
        config: MewCodeConfig,
        session: ChatSession | None = None,
        agent: SingleToolAgent | None = None,
        input_func=None,
        output: TextIO = sys.stdout,
        cwd: Path | None = None,
        version: str = __version__,
        mcp_status_provider: Callable[[], dict[str, int]] | None = None,
    ) -> None:
        self.provider = provider
        self.config = config
        self.session = session or ChatSession()
        self.agent = agent
        self.input_func = input_func
        self.output = output
        self.cwd = cwd or Path.cwd()
        self.version = version
        self.mcp_status_provider = mcp_status_provider
        self.command_registry: CommandRegistry = make_builtin_registry()
        self.pending_request: PendingToolRequest | None = None
        self.mode = "normal"
        self.permission_mode = config.permission_mode
        self.last_plan_path: str | None = None

    def run(self) -> int:
        if (
            self.input_func is not None
            or not sys.stdin.isatty()
            or not sys.stdout.isatty()
            or should_use_line_mode_for_terminal()
        ):
            return self._run_line_mode()
        app = MewCodeApp(
            provider=self.provider,
            config=self.config,
            session=self.session,
            agent=self.agent,
            cwd=self.cwd,
            version=self.version,
            mcp_status_provider=self.mcp_status_provider,
        )
        result = app.run()
        return int(result or 0)

    def header_text(self) -> str:
        parts = [
            f"MewCode Agent v{self.version}",
            model_status_line(self.config),
            agent_mode_status_line(self.mode),
            permission_status_line(self.permission_mode),
        ]
        mcp_line = self._mcp_status_line()
        if mcp_line:
            parts.append(mcp_line)
        parts.append(f"cwd:{self.cwd}")
        return "  ".join(parts)

    def _mcp_status_line(self) -> str:
        if self.mcp_status_provider is None:
            return ""
        return mcp_status_line(self.mcp_status_provider())

    def _run_line_mode(self) -> int:
        self._println(self.header_text())
        self._println(f"{LINE_MODE_HINT}{FOOTER_HINT}")
        while True:
            try:
                user_input = self.input_func("> ") if self.input_func else input("> ")
            except (EOFError, KeyboardInterrupt):
                self._println("\nBye.")
                return 0
            content = user_input.strip()
            if not content:
                continue
            if content in {"/exit", "/quit"}:
                self._println("Bye.")
                return 0
            command_result = self._dispatch_slash_command(content)
            if command_result is not None:
                self._handle_line_command_result(command_result, content)
                continue

            if self.agent is None:
                self._println("* Error: No agent configured")
                continue

            if self.pending_request is not None:
                pending = self.pending_request
                lowered = content.lower()
                if lowered in {"y", "yes"}:
                    self.pending_request = None
                    events = self.agent.stream_confirm(self.session, pending)
                elif lowered in {"a", "always", "permanent", "forever"}:
                    self.pending_request = None
                    events = self.agent.stream_confirm(self.session, pending, scope="permanent")
                elif lowered in {"n", "no"}:
                    self.pending_request = None
                    events = self.agent.stream_deny(self.session, pending)
                else:
                    self._println("Please reply yes, always, or no.")
                    continue
                for event in events:
                    self._handle_line_event(event)
                continue

            self._println(f"> {content}")
            for event in self._agent_stream_turn(content):
                self._handle_line_event(event)

    def _dispatch_slash_command(self, text: str) -> CommandResult | None:
        return self.command_registry.dispatch(
            text,
            CommandContext(mode=self.mode, permission_mode=self.permission_mode, registry=self.command_registry),
        )

    def _handle_line_command_result(self, result: CommandResult, original_text: str) -> None:
        if result.action == "message":
            self._println(result.message)
            return
        if result.action == "clear":
            self._println("\033[2J\033[H* Screen cleared")
            return
        if result.action == "copy":
            self._println("* Copy commands are available in TUI. Use terminal selection in line mode.")
            return
        if result.action == "accept":
            self.mode = "normal"
            self._println(accept_plan_status_plain(self.last_plan_path))
            return
        if result.action == "set_mode":
            self.mode = result.mode or "normal"
            self._println(mode_status_plain(self.mode))
            if result.remainder:
                self._send_line_agent_text(result.remainder)
            return
        if result.action == "permission_status":
            self._println(permission_options_plain(self.permission_mode))
            return
        if result.action == "set_permission":
            if result.permission_mode is not None:
                self._set_line_permission_mode(result.permission_mode)
            self._println(permission_mode_status_plain(self.permission_mode))
            return
        if result.action == "status":
            self._println(self._line_runtime_status_text())
            return
        if result.action == "compact":
            if self.agent is None:
                self._println("* Error: No agent configured")
                return
            for event in self._agent_stream_compact(result.focus):
                self._handle_line_event(event)
            return
        if result.action == "context":
            if self.agent is None:
                self._println("* Error: No agent configured")
                return
            for event in self._agent_stream_context_stats():
                self._handle_line_event(event)
            return
        if result.action == "memory":
            if self.agent is None:
                self._println("* Error: No agent configured")
                return
            for event in self._agent_stream_memory_command(result.command_line):
                self._handle_line_event(event)
            return
        if result.action == "agent_prompt":
            self._send_line_agent_text(result.prompt, display_text=original_text)

    def _send_line_agent_text(self, text: str, display_text: str | None = None) -> None:
        if self.agent is None:
            self._println("* Error: No agent configured")
            return
        self._println(f"> {display_text or text}")
        for event in self._agent_stream_turn(text):
            self._handle_line_event(event)

    def _set_line_permission_mode(self, mode: PermissionMode) -> None:
        self.permission_mode = mode
        checker = getattr(self.agent, "permission_checker", None)
        if checker is not None:
            checker.set_mode(self.permission_mode)

    def _line_runtime_status_text(self) -> str:
        lines = [
            "MewCode status",
            f"- model: {model_status_line(self.config)}",
            f"- cwd: {self.cwd}",
            f"- agent mode: {agent_mode_label(self.mode)}",
            f"- permission: {self.permission_mode}",
        ]
        mcp_line = self._mcp_status_line()
        if mcp_line:
            lines.append(f"- mcp: {mcp_line}")
        context_manager = getattr(self.agent, "context_manager", None)
        if context_manager is not None:
            tokens = context_manager.estimate_session_tokens(self.session)
            window = context_manager.config.context_window_tokens
            lines.append(f"- context: {tokens}/{window} estimated session tokens")
        else:
            lines.append("- context: not configured")
        memory_manager = getattr(self.agent, "memory_manager", None)
        if memory_manager is not None:
            counts = memory_manager.status_counts()
            lines.append(
                "- memory: "
                f"{counts.get('memories', 0)} memories, {counts.get('sessions', 0)} sessions, "
                f"auto={'on' if counts.get('auto_memory_enabled') else 'off'}"
            )
        else:
            lines.append("- memory: not configured")
        return "\n".join(lines)

    def _agent_stream_turn(self, content: str) -> Iterator[AgentEvent]:
        if self.agent is None:
            return iter(())
        try:
            return self.agent.stream_turn(self.session, content, mode=self.mode)
        except TypeError:
            return self.agent.stream_turn(self.session, content)

    def _agent_stream_compact(self, focus: str = "") -> Iterator[AgentEvent]:
        if self.agent is None:
            return iter(())
        compact = getattr(self.agent, "stream_compact", None)
        if compact is None:
            return iter(())
        try:
            return compact(self.session, focus=focus)
        except TypeError:
            return compact(self.session)

    def _agent_stream_context_stats(self) -> Iterator[AgentEvent]:
        if self.agent is None:
            return iter(())
        stats = getattr(self.agent, "stream_context_stats", None)
        if stats is None:
            return iter(())
        try:
            return stats(self.session, mode=self.mode)
        except TypeError:
            return stats(self.session)

    def _agent_stream_memory_command(self, text: str) -> Iterator[AgentEvent]:
        if self.agent is None:
            return iter(())
        command = getattr(self.agent, "stream_memory_command", None)
        if command is None:
            return iter(())
        return command(self.session, text)

    def _handle_line_event(self, event: AgentEvent) -> None:
        if isinstance(event, TextDelta):
            self._println(event.text)
        elif isinstance(event, ToolStarted):
            self._println(f"* Running {tool_action_label(event.tool_call)}")
        elif isinstance(
            event,
            (
                ContextCompressionStarted,
                ContextCompressionFinished,
                ContextCompressionFailed,
                ContextCompressionFallbackUsed,
                ContextChunkSummaryStarted,
                ContextChunkSummaryFinished,
                ContextStatsReported,
                ContextCompressionSkipped,
                ContextEmergencyRetry,
            ),
        ):
            text = context_event_plain(event)
            if text:
                self._println(text)
        elif isinstance(event, ToolFinished):
            ok = bool(event.result.get("ok"))
            self._remember_plan_file(event.result)
            status = "ok" if ok else f"failed: {event.result.get('error') or event.result.get('content') or ''}"
            self._println(f"* {tool_action_label(event.tool_call)} {status}")
            if tool_result_updates_mcp_status(event.result):
                mcp_line = self._mcp_status_line()
                if mcp_line:
                    self._println(f"* {mcp_line}")
        elif isinstance(event, ToolResultSpilled):
            self._println(f"* {tool_result_spilled_plain(event)}")
        elif isinstance(event, MemoryCommandResult):
            self._println(event.content)
        elif isinstance(event, MemoryUpdated):
            self._println(f"* Memory updated ({event.count} item(s))")
        elif isinstance(event, ConfirmationRequired):
            self.pending_request = event.pending_request
            self._println(confirmation_status_plain(event.pending_request.tool_call.name))
        elif isinstance(event, UserQuestionRequested):
            if should_render_structured_clarification(event):
                self._println(clarification_questions_text(event.questions))
            else:
                self._println(question_message_text(event.question, event.options))
            self._println("* Waiting for your clarification. Reply with the answer to continue planning.")
        elif isinstance(event, TurnCancelled):
            self._println("* Interrupted")
        elif isinstance(event, AgentError):
            self._println(f"* Error: {event.message}")
        elif isinstance(event, TurnComplete):
            if event.reason != "await_user":
                self._println(f"* Done ({event.reason})")

    def _remember_plan_file(self, result: dict) -> None:
        metadata = result.get("metadata") or {}
        if not metadata.get("plan_file"):
            return
        path = metadata.get("relative_path") or metadata.get("path")
        if path:
            self.last_plan_path = str(path)

    def _println(self, text: str) -> None:
        print(text, flush=True, file=self.output)
