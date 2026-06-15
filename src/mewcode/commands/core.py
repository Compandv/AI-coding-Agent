from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal, Protocol

from mewcode.permissions import PERMISSION_MODES, PermissionMode, validate_permission_mode


CommandKind = Literal["local", "ui", "prompt"]
CommandAction = Literal[
    "message",
    "clear",
    "compact",
    "context",
    "memory",
    "set_mode",
    "permission_status",
    "set_permission",
    "status",
    "agent_prompt",
    "copy",
    "accept",
]


class CommandConflictError(ValueError):
    """Raised when a slash command name or alias is registered twice."""


class UIController(Protocol):
    """Minimal UI operations a command dispatcher can target."""

    def show_message(self, text: str) -> None: ...

    def clear_display(self) -> None: ...

    def set_agent_mode(self, mode: str) -> None: ...

    def set_permission_mode(self, mode: PermissionMode) -> None: ...

    def send_agent_message(self, text: str) -> None: ...


@dataclass(frozen=True)
class CommandInvocation:
    raw: str
    token: str
    args: str


@dataclass(frozen=True)
class CommandContext:
    mode: str = "normal"
    permission_mode: PermissionMode = "default"
    registry: "CommandRegistry | None" = None


@dataclass(frozen=True)
class CommandResult:
    action: CommandAction
    message: str = ""
    mode: str = ""
    remainder: str = ""
    focus: str = ""
    command_line: str = ""
    permission_mode: PermissionMode | None = None
    copy_target: str = ""
    prompt: str = ""


CommandHandler = Callable[[CommandContext, CommandInvocation], CommandResult]


@dataclass(frozen=True)
class CommandDefinition:
    name: str
    description: str
    usage: str
    kind: CommandKind
    handler: CommandHandler
    aliases: tuple[str, ...] = ()
    argument_hint: str = ""
    hidden: bool = False

    @property
    def normalized_name(self) -> str:
        return normalize_command_name(self.name)

    @property
    def normalized_aliases(self) -> tuple[str, ...]:
        return tuple(normalize_command_name(alias) for alias in self.aliases)


@dataclass(frozen=True)
class ParsedCommand:
    token: str
    args: str


def normalize_command_name(name: str) -> str:
    return name.strip().removeprefix("/").lower()


def parse_command_line(text: str) -> ParsedCommand | None:
    stripped = text.strip()
    if not stripped or not stripped.startswith("/"):
        return None
    without_slash = stripped[1:]
    if not without_slash:
        return ParsedCommand("", "")
    token, _, args = without_slash.partition(" ")
    return ParsedCommand(normalize_command_name(token), args.strip())


class CommandRegistry:
    def __init__(self) -> None:
        self._definitions: list[CommandDefinition] = []
        self._lookup: dict[str, CommandDefinition] = {}

    def register(self, definition: CommandDefinition) -> None:
        names = (definition.normalized_name, *definition.normalized_aliases)
        for name in names:
            if not name:
                raise CommandConflictError("Command names and aliases cannot be empty.")
            if name in self._lookup:
                existing = self._lookup[name].name
                raise CommandConflictError(f"Command name or alias '{name}' conflicts with '{existing}'.")
        self._definitions.append(definition)
        for name in names:
            self._lookup[name] = definition

    def get(self, name: str) -> CommandDefinition | None:
        return self._lookup.get(normalize_command_name(name))

    def visible(self) -> list[CommandDefinition]:
        return [definition for definition in self._definitions if not definition.hidden]

    def complete(self, text: str) -> list[str]:
        parsed = parse_command_line(text)
        if parsed is None or " " in text.strip():
            return []
        prefix = parsed.token
        candidates: list[str] = []
        for definition in self.visible():
            names = (definition.normalized_name, *definition.normalized_aliases)
            if any(name.startswith(prefix) for name in names):
                candidates.append(f"/{definition.name} ")
        return sorted(set(candidates))

    def help_text(self) -> str:
        lines = ["Available commands:"]
        for definition in self.visible():
            aliases = f" aliases: {', '.join('/' + alias for alias in definition.aliases)}" if definition.aliases else ""
            lines.append(f"- /{definition.name}: {definition.description}")
            lines.append(f"  usage: {definition.usage}{aliases}")
        return "\n".join(lines)

    def dispatch(self, text: str, context: CommandContext | None = None) -> CommandResult | None:
        parsed = parse_command_line(text)
        if parsed is None:
            return None
        invocation = CommandInvocation(raw=text.strip(), token=parsed.token, args=parsed.args)
        definition = self.get(invocation.token)
        if definition is None:
            token = f"/{invocation.token}" if invocation.token else "/"
            return CommandResult("message", message=f"Unknown command: {token}. Type /help for available commands.")
        active_context = context or CommandContext(registry=self)
        if active_context.registry is None:
            active_context = CommandContext(
                mode=active_context.mode,
                permission_mode=active_context.permission_mode,
                registry=self,
            )
        return definition.handler(active_context, invocation)


def make_builtin_registry() -> CommandRegistry:
    registry = CommandRegistry()
    for definition in builtin_definitions():
        registry.register(definition)
    return registry


def builtin_definitions() -> list[CommandDefinition]:
    return [
        CommandDefinition("help", "Show available slash commands.", "/help", "local", _help, aliases=("?",)),
        CommandDefinition("compact", "Compact the current conversation context.", "/compact [focus <text>]", "local", _compact),
        CommandDefinition("clear", "Clear the current screen without changing conversation state.", "/clear", "ui", _clear, aliases=("cls",)),
        CommandDefinition("plan", "Switch to Plan Mode, optionally sending the rest as a task.", "/plan [task]", "ui", _plan),
        CommandDefinition("do", "Switch back to normal execution mode, optionally sending the rest as a task.", "/do [task]", "ui", _do),
        CommandDefinition("session", "Manage saved sessions.", "/session <list|current|resume|delete|rename>", "local", _memory_command),
        CommandDefinition("memory", "Manage cross-session memory.", "/memory <list|refresh|on|off|delete>", "local", _memory_command),
        CommandDefinition("permission", "Show or switch permission mode.", "/permission [default|acceptEdits|plan|bypassPermissions]", "ui", _permission, aliases=("perm",)),
        CommandDefinition("status", "Show local runtime status.", "/status", "local", _status),
        CommandDefinition("review", "Review the current Git working tree changes.", "/review [focus]", "prompt", _review),
        CommandDefinition("context", "Show context token stats.", "/context", "local", _context, hidden=True),
        CommandDefinition("accept", "Accept the current plan.", "/accept", "ui", _accept, hidden=True),
        CommandDefinition("copy", "Copy transcript or last answer in TUI.", "/copy [last|transcript]", "ui", _copy, hidden=True),
    ]


def _help(context: CommandContext, invocation: CommandInvocation) -> CommandResult:
    registry = context.registry
    return CommandResult("message", message=registry.help_text() if registry is not None else "No commands registered.")


def _compact(context: CommandContext, invocation: CommandInvocation) -> CommandResult:
    if not invocation.args:
        return CommandResult("compact", focus="")
    lowered = invocation.args.lower()
    if lowered.startswith("focus "):
        return CommandResult("compact", focus=invocation.args[6:].strip())
    return CommandResult("message", message="Usage: /compact [focus <text>]")


def _clear(context: CommandContext, invocation: CommandInvocation) -> CommandResult:
    return CommandResult("clear")


def _plan(context: CommandContext, invocation: CommandInvocation) -> CommandResult:
    return CommandResult("set_mode", mode="plan", remainder=invocation.args)


def _do(context: CommandContext, invocation: CommandInvocation) -> CommandResult:
    return CommandResult("set_mode", mode="normal", remainder=invocation.args)


def _memory_command(context: CommandContext, invocation: CommandInvocation) -> CommandResult:
    return CommandResult("memory", command_line=invocation.raw)


def _permission(context: CommandContext, invocation: CommandInvocation) -> CommandResult:
    if not invocation.args:
        return CommandResult("permission_status")
    aliases = {
        "edit": "acceptEdits",
        "acceptedits": "acceptEdits",
        "bypass": "bypassPermissions",
        "bypasspermissions": "bypassPermissions",
        "default": "default",
        "plan": "plan",
    }
    candidate = aliases.get(invocation.args.strip().lower(), invocation.args.strip())
    try:
        mode = validate_permission_mode(candidate)
    except Exception:
        options = ", ".join(PERMISSION_MODES)
        return CommandResult("message", message=f"Unknown permission mode: {invocation.args}. Available modes: {options}.")
    return CommandResult("set_permission", permission_mode=mode)


def _status(context: CommandContext, invocation: CommandInvocation) -> CommandResult:
    return CommandResult("status")


def _review(context: CommandContext, invocation: CommandInvocation) -> CommandResult:
    return CommandResult("agent_prompt", prompt=review_prompt(invocation.args))


def _context(context: CommandContext, invocation: CommandInvocation) -> CommandResult:
    return CommandResult("context")


def _accept(context: CommandContext, invocation: CommandInvocation) -> CommandResult:
    return CommandResult("accept")


def _copy(context: CommandContext, invocation: CommandInvocation) -> CommandResult:
    lowered = invocation.args.lower()
    if lowered in {"", "transcript"}:
        return CommandResult("copy", copy_target="transcript")
    if lowered in {"last", "answer", "last-answer"}:
        return CommandResult("copy", copy_target="last")
    return CommandResult("message", message="Usage: /copy [last|transcript]")


def review_prompt(focus: str = "") -> str:
    prompt = (
        "Review the current Git working tree changes. Use a code-review stance: findings first, "
        "ordered by severity, with file and line references when possible. Read the relevant diff "
        "and files before judging. If you find no issues, say that clearly and mention any residual "
        "test gaps or risk. Keep the summary secondary."
    )
    stripped = focus.strip()
    if stripped:
        prompt = f"{prompt}\n\nReview focus: {stripped}"
    return prompt
