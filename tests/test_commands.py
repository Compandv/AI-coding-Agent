import pytest

from mewcode.commands import (
    CommandConflictError,
    CommandContext,
    CommandDefinition,
    CommandRegistry,
    make_builtin_registry,
    parse_command_line,
)
from mewcode.skills import SkillManager
from mewcode.tools import default_registry


def noop(context, invocation):
    from mewcode.commands import CommandResult

    return CommandResult("message", message="ok")


def test_parse_command_line_is_case_insensitive_and_preserves_args():
    parsed = parse_command_line("/COMPACT focus keep context.py")

    assert parsed is not None
    assert parsed.token == "compact"
    assert parsed.args == "focus keep context.py"
    assert parse_command_line("hello") is None
    assert parse_command_line("") is None


def test_registry_detects_name_and_alias_conflicts():
    registry = CommandRegistry()
    registry.register(CommandDefinition("clear", "Clear", "/clear", "local", noop, aliases=("cls",)))

    with pytest.raises(CommandConflictError):
        registry.register(CommandDefinition("cls", "Conflict", "/cls", "local", noop))
    with pytest.raises(CommandConflictError):
        registry.register(CommandDefinition("copy", "Conflict", "/copy", "local", noop, aliases=("clear",)))


def test_builtin_registry_help_and_completion_hide_compat_commands():
    registry = make_builtin_registry()

    help_text = registry.dispatch("/help", CommandContext(registry=registry)).message

    assert "/help" in help_text
    assert "/review" in help_text
    assert "/context" not in help_text
    assert registry.complete("/c") == ["/clear ", "/compact "]
    assert registry.complete("/cont") == []
    assert registry.complete("/perm") == ["/permission "]


def test_unknown_slash_command_is_local_error():
    registry = make_builtin_registry()

    result = registry.dispatch("/missing", CommandContext(registry=registry))

    assert result is not None
    assert result.action == "message"
    assert "/help" in result.message


def test_builtin_commands_return_expected_actions():
    registry = make_builtin_registry()

    assert registry.dispatch("/compact").action == "compact"
    assert registry.dispatch("/compact focus keep details").focus == "keep details"
    assert registry.dispatch("/plan inspect").remainder == "inspect"
    assert registry.dispatch("/do implement").mode == "normal"
    assert registry.dispatch("/session current").action == "memory"
    assert registry.dispatch("/memory list").command_line == "/memory list"
    assert registry.dispatch("/permission acceptEdits").permission_mode == "acceptEdits"
    assert registry.dispatch("/permission nope").action == "message"
    assert registry.dispatch("/status").action == "status"
    assert "Git working tree" in registry.dispatch("/review").prompt


def test_skill_commands_are_registered_when_skill_manager_is_available(tmp_path):
    manager = SkillManager(tmp_path / "project", default_registry(), user_home=tmp_path / "home")
    manager.load()
    registry = make_builtin_registry(manager)

    help_text = registry.dispatch("/help", CommandContext(registry=registry)).message
    result = registry.dispatch("/review focus auth", CommandContext(registry=registry))

    assert "/commit" in help_text
    assert "/commit " in registry.complete("/com")
    assert result.action == "skill_prompt"
    assert result.skill_name == "review"
    assert result.arguments == "focus auth"
    assert registry.dispatch("/skill list").action == "skill"
