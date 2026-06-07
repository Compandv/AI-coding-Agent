import pytest

from mewcode.permissions import (
    PermissionChecker,
    PermissionError,
    PermissionRule,
    PermissionRuleSet,
    is_broad_env_read_path,
    is_dangerous_command,
    load_rules_file,
    normalize_rules,
)
from mewcode.providers.base import ToolCall
from mewcode.tools.context import ToolContext


def checker(tmp_path, mode="default", rules=None):
    return PermissionChecker(context=ToolContext(root_dir=tmp_path), mode=mode, rules=rules or PermissionRuleSet())


def test_dangerous_command_detector_blocks_known_destructive_commands():
    assert is_dangerous_command("rm -rf /")
    assert is_dangerous_command("rm -rf C:\\")
    assert is_dangerous_command("del /s /q C:\\*")
    assert is_dangerous_command("format C:")
    assert is_dangerous_command("mkfs /dev/sda")
    assert is_dangerous_command("shutdown /s")
    assert is_dangerous_command("shutdown -h now")


def test_dangerous_command_cannot_be_allowed_by_rule(tmp_path):
    rules = PermissionRuleSet(user_rules=[PermissionRule("Bash", "rm *", "allow", "user")])
    decision = checker(tmp_path, mode="bypassPermissions", rules=rules).check(
        ToolCall(name="Bash", arguments={"command": "rm -rf /"})
    )

    assert decision.action == "deny"
    assert decision.metadata["blocked_by_dangerous_command"] is True


def test_path_sandbox_blocks_escape_before_hitl(tmp_path):
    decision = checker(tmp_path, mode="bypassPermissions").check(
        ToolCall(name="WriteFile", arguments={"path": "../outside.txt", "content": "x"})
    )

    assert decision.action == "deny"
    assert decision.metadata["blocked_by_sandbox"] is True


def test_readfile_blocks_broad_env_wildcard_and_suggests_exact_candidates(tmp_path):
    decision = checker(tmp_path, mode="bypassPermissions").check(
        ToolCall(name="ReadFile", arguments={"path": "*.env*"})
    )

    assert decision.action == "deny"
    assert decision.metadata["blocked_by_sensitive_read_pattern"] is True
    assert decision.metadata["suggested_paths"] == [
        ".env",
        ".env.local",
        ".env.example",
        ".env.development",
        ".env.production",
    ]


def test_readfile_allows_exact_env_filename(tmp_path):
    decision = checker(tmp_path).check(ToolCall(name="ReadFile", arguments={"path": ".env"}))

    assert decision.action == "allow"


def test_broad_env_path_detection_only_matches_env_wildcards():
    assert is_broad_env_read_path("*.env*")
    assert is_broad_env_read_path("**/.env.*")
    assert not is_broad_env_read_path(".env")
    assert not is_broad_env_read_path("src/*.py")


def test_rule_matching_prefers_local_over_project_and_project_over_user(tmp_path):
    rules = PermissionRuleSet(
        user_rules=[PermissionRule("Bash", "git *", "allow", "user")],
        project_rules=[PermissionRule("Bash", "git *", "deny", "project")],
        local_rules=[PermissionRule("Bash", "git *", "allow", "local")],
    )

    decision = checker(tmp_path, rules=rules).check(ToolCall(name="Bash", arguments={"command": "git status"}))

    assert decision.action == "allow"
    assert decision.rule.source == "local"


def test_same_layer_deny_wins_over_allow(tmp_path):
    rules = PermissionRuleSet(
        project_rules=[
            PermissionRule("Bash", "git *", "allow", "project"),
            PermissionRule("Bash", "git status", "deny", "project"),
        ]
    )

    decision = checker(tmp_path, rules=rules).check(ToolCall(name="Bash", arguments={"command": "git status"}))

    assert decision.action == "deny"
    assert decision.rule.result == "deny"


def test_permission_modes_default_accept_edits_plan_and_bypass(tmp_path):
    assert checker(tmp_path, "default").check(ToolCall(name="ReadFile", arguments={"path": "a.txt"})).action == "allow"
    assert checker(tmp_path, "default").check(ToolCall(name="WriteFile", arguments={"path": "a.txt"})).action == "ask"
    assert checker(tmp_path, "acceptEdits").check(ToolCall(name="EditFile", arguments={"path": "a.txt"})).action == "allow"
    assert checker(tmp_path, "acceptEdits").check(ToolCall(name="Bash", arguments={"command": "pytest"})).action == "ask"
    assert checker(tmp_path, "plan").check(ToolCall(name="WriteFile", arguments={"path": "a.txt"})).action == "deny"
    assert checker(tmp_path, "bypassPermissions").check(ToolCall(name="Bash", arguments={"command": "git status"})).action == "allow"



def test_load_rules_file_accepts_rules_mapping(tmp_path):
    path = tmp_path / "permissions.yaml"
    path.write_text(
        """
rules:
  Bash(git *): allow
  WriteFile(docs/*.md): deny
""",
        encoding="utf-8",
    )

    rules = load_rules_file(path, "project")

    assert [rule.expression for rule in rules] == ["Bash(git *)", "WriteFile(docs/*.md)"]
    assert [rule.result for rule in rules] == ["allow", "deny"]


def test_invalid_rule_result_is_rejected():
    with pytest.raises(PermissionError):
        normalize_rules({"Bash(git *)": "maybe"}, "user")


def test_permanent_allow_writes_local_rules_file(tmp_path):
    local_path = tmp_path / ".mewcode" / "permissions.local.yaml"
    rules = PermissionRuleSet(local_path=local_path)
    rule = rules.add_local_allow(ToolCall(name="Bash", arguments={"command": "git status"}))

    assert rule.expression == "Bash(git status)"
    content = local_path.read_text(encoding="utf-8")
    assert "Bash(git status): allow" in content
