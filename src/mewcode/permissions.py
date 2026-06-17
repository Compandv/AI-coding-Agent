from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from mewcode.tools import ToolContext, ToolError


PermissionMode = Literal["default", "acceptEdits", "plan", "bypassPermissions"]
RuleResult = Literal["allow", "deny"]
DecisionAction = Literal["allow", "deny", "ask"]
ConfirmScope = Literal["once", "permanent"]

PERMISSION_MODES: tuple[PermissionMode, ...] = ("default", "acceptEdits", "plan", "bypassPermissions")
DEFAULT_PERMISSION_MODE: PermissionMode = "default"

USER_PERMISSIONS_PATH = Path.home() / ".mewcode" / "permissions.yaml"
PROJECT_PERMISSIONS_PATH = Path(".mewcode") / "permissions.yaml"
LOCAL_PERMISSIONS_PATH = Path(".mewcode") / "permissions.local.yaml"

READ_TOOLS = {"ReadFile", "Glob", "Grep", "AskUserQuestion", "ListMCPServers", "ListSkills", "LoadSkill", "ActivateSkill"}
EDIT_TOOLS = {"WriteFile", "EditFile", "WritePlanFile"}
UNSAFE_TOOLS = {"WriteFile", "EditFile", "WritePlanFile", "Bash", "ActivateMCPServer"}
COMMON_ENV_FILENAMES = (".env", ".env.local", ".env.example", ".env.development", ".env.production")
GLOB_META_CHARS = ("*", "?", "[")

DANGEROUS_COMMAND_PATTERNS = [
    re.compile(r"(?i)(^|[;&|]\s*)rm\s+(-[^\s]*[rf][^\s]*|-r\s+-f|-f\s+-r)\s+(/|/\*|[a-z]:\\?)(\s|$)"),
    re.compile(r"(?i)(^|[;&|]\s*)del\s+(/s\s+)?(/q\s+)?[a-z]:\\\*"),
    re.compile(r"(?i)(^|[;&|]\s*)format\s+[a-z]:"),
    re.compile(r"(?i)(^|[;&|]\s*)shutdown\s+(/s|-h\s+now|-r)"),
    re.compile(r"(?i)(^|[;&|]\s*)mkfs(\.|\s)"),
    re.compile(r"(?i)(^|[;&|]\s*)dd\s+.*\bof=/dev/(sd|hd|nvme)"),
    re.compile(r"\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;"),
]


class PermissionError(Exception):
    """Raised when permission configuration cannot be loaded."""


@dataclass(frozen=True)
class PermissionRule:
    tool_name: str
    pattern: str
    result: RuleResult
    source: str = ""

    @property
    def expression(self) -> str:
        return f"{self.tool_name}({self.pattern})"


@dataclass(frozen=True)
class PermissionDecision:
    action: DecisionAction
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)
    rule: PermissionRule | None = None

    @classmethod
    def allow(cls, reason: str, **metadata: Any) -> "PermissionDecision":
        return cls("allow", reason, metadata)

    @classmethod
    def deny(cls, reason: str, **metadata: Any) -> "PermissionDecision":
        return cls("deny", reason, metadata)

    @classmethod
    def ask(cls, reason: str, **metadata: Any) -> "PermissionDecision":
        return cls("ask", reason, metadata)


@dataclass
class PermissionRuleSet:
    user_rules: list[PermissionRule] = field(default_factory=list)
    project_rules: list[PermissionRule] = field(default_factory=list)
    local_rules: list[PermissionRule] = field(default_factory=list)
    local_path: Path | None = None

    def match(self, tool_call: Any) -> PermissionRule | None:
        target = tool_match_target(tool_call)
        for rules in (self.local_rules, self.project_rules, self.user_rules):
            matched = [rule for rule in rules if rule_matches(rule, tool_call.name, target)]
            deny = next((rule for rule in matched if rule.result == "deny"), None)
            if deny is not None:
                return deny
            allow = next((rule for rule in matched if rule.result == "allow"), None)
            if allow is not None:
                return allow
        return None

    def add_local_allow(self, tool_call: Any) -> PermissionRule:
        rule = PermissionRule(tool_call.name, exact_rule_pattern(tool_call), "allow", "local")
        self.local_rules.append(rule)
        if self.local_path is not None:
            save_rules_file(self.local_path, self.local_rules)
        return rule


@dataclass
class PermissionChecker:
    context: ToolContext
    mode: PermissionMode = DEFAULT_PERMISSION_MODE
    rules: PermissionRuleSet = field(default_factory=PermissionRuleSet)
    read_tools: set[str] = field(default_factory=lambda: set(READ_TOOLS))
    edit_tools: set[str] = field(default_factory=lambda: set(EDIT_TOOLS))
    unsafe_tools: set[str] = field(default_factory=lambda: set(UNSAFE_TOOLS))

    @classmethod
    def from_workspace(
        cls,
        context: ToolContext,
        mode: PermissionMode = DEFAULT_PERMISSION_MODE,
        user_path: Path = USER_PERMISSIONS_PATH,
    ) -> "PermissionChecker":
        root = context.root_dir
        project_path = root / PROJECT_PERMISSIONS_PATH
        local_path = root / LOCAL_PERMISSIONS_PATH
        return cls(
            context=context,
            mode=validate_permission_mode(mode),
            rules=PermissionRuleSet(
                user_rules=load_rules_file(user_path, "user"),
                project_rules=load_rules_file(project_path, "project"),
                local_rules=load_rules_file(local_path, "local"),
                local_path=local_path,
            ),
        )

    def add_read_tools(self, tool_names: set[str]) -> None:
        self.read_tools.update(tool_names)
        self.unsafe_tools.difference_update(tool_names)

    def set_mode(self, mode: PermissionMode) -> None:
        self.mode = validate_permission_mode(mode)

    def cycle_mode(self) -> PermissionMode:
        index = PERMISSION_MODES.index(self.mode)
        self.mode = PERMISSION_MODES[(index + 1) % len(PERMISSION_MODES)]
        return self.mode

    def check(self, tool_call: Any) -> PermissionDecision:
        if tool_call.name == "Bash":
            command = str(tool_call.arguments.get("command") or "")
            if is_dangerous_command(command):
                return PermissionDecision.deny(
                    f"Dangerous command blocked: {command}",
                    blocked_by_dangerous_command=True,
                    tool_name=tool_call.name,
                )

        sandbox = self._sandbox_decision(tool_call)
        if sandbox is not None:
            return sandbox

        sensitive_read = self._sensitive_read_decision(tool_call)
        if sensitive_read is not None:
            return sensitive_read

        rule = self.rules.match(tool_call)
        if rule is not None:
            if rule.result == "allow":
                return PermissionDecision("allow", f"Allowed by rule {rule.expression}", {"allowed_by_rule": True}, rule)
            return PermissionDecision("deny", f"Denied by rule {rule.expression}", {"blocked_by_rule": True}, rule)

        return self._mode_decision(tool_call)

    def allow_permanently(self, tool_call: Any) -> PermissionRule:
        return self.rules.add_local_allow(tool_call)

    def _sandbox_decision(self, tool_call: Any) -> PermissionDecision | None:
        raw_path = path_argument(tool_call)
        if raw_path is None:
            return None
        try:
            self.context.resolve_path(raw_path)
        except ToolError as exc:
            return PermissionDecision.deny(
                str(exc),
                blocked_by_sandbox=True,
                tool_name=tool_call.name,
                path=raw_path,
            )
        return None

    def _sensitive_read_decision(self, tool_call: Any) -> PermissionDecision | None:
        if tool_call.name != "ReadFile":
            return None
        raw_path = str(tool_call.arguments.get("path") or "")
        if not is_broad_env_read_path(raw_path):
            return None
        return PermissionDecision.deny(
            (
                f"ReadFile({raw_path}) is too broad for environment files. "
                "ReadFile only accepts one explicit file path. "
                f"Try these common candidates one by one: {', '.join(COMMON_ENV_FILENAMES)}."
            ),
            blocked_by_sensitive_read_pattern=True,
            tool_name=tool_call.name,
            path=raw_path,
            suggested_paths=list(COMMON_ENV_FILENAMES),
        )

    def _mode_decision(self, tool_call: Any) -> PermissionDecision:
        name = tool_call.name
        if self.mode == "plan":
            if name in self.read_tools:
                return PermissionDecision.allow("Allowed read-only tool in plan mode", allowed_by_mode=self.mode)
            return PermissionDecision.deny(
                f"Permission mode plan blocks tool: {name}",
                blocked_by_permission_mode=True,
                permission_mode=self.mode,
            )

        if self.mode == "bypassPermissions":
            return PermissionDecision.allow("Allowed by bypassPermissions mode", allowed_by_mode=self.mode)

        if name in self.read_tools:
            return PermissionDecision.allow("Allowed safe read tool", allowed_by_mode=self.mode)

        if self.mode == "acceptEdits" and name in self.edit_tools:
            return PermissionDecision.allow("Allowed edit tool by acceptEdits mode", allowed_by_mode=self.mode)

        return PermissionDecision.ask(
            f"Permission required for {name}",
            requires_hitl=True,
            permission_mode=self.mode,
            tool_name=name,
        )


def validate_permission_mode(value: str | None) -> PermissionMode:
    mode = (value or DEFAULT_PERMISSION_MODE).strip()
    if mode not in PERMISSION_MODES:
        raise PermissionError(f"Unknown permission mode: {value}")
    return mode  # type: ignore[return-value]


def is_dangerous_command(command: str) -> bool:
    return any(pattern.search(command.strip()) for pattern in DANGEROUS_COMMAND_PATTERNS)


def is_broad_env_read_path(path: str) -> bool:
    normalized = normalize_target(path).lower()
    return ".env" in normalized and any(char in normalized for char in GLOB_META_CHARS)


def load_rules_file(path: Path, source: str) -> list[PermissionRule]:
    if not path.exists():
        return []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PermissionError(f"Failed to parse permission rules {path}: {exc}") from exc
    except OSError as exc:
        raise PermissionError(f"Failed to read permission rules {path}: {exc}") from exc
    return normalize_rules(raw, source)


def normalize_rules(raw: Any, source: str) -> list[PermissionRule]:
    if raw is None:
        return []
    if isinstance(raw, dict) and "rules" in raw:
        raw = raw["rules"]

    items: list[tuple[str, Any]] = []
    if isinstance(raw, dict):
        items = [(str(key), value) for key, value in raw.items()]
    elif isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                raise PermissionError("Permission rule list items must be mappings.")
            expression = item.get("rule") or item.get("pattern")
            result = item.get("result") or item.get("action")
            items.append((str(expression or ""), result))
    else:
        raise PermissionError("Permission rules must be a mapping or a list.")

    rules: list[PermissionRule] = []
    for expression, raw_result in items:
        result = str(raw_result or "").strip().lower()
        if result not in {"allow", "deny"}:
            raise PermissionError(f"Permission rule {expression} must be allow or deny.")
        tool_name, pattern = parse_rule_expression(expression)
        rules.append(PermissionRule(tool_name=tool_name, pattern=pattern, result=result, source=source))  # type: ignore[arg-type]
    return rules


def save_rules_file(path: Path, rules: list[PermissionRule]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"rules": {rule.expression: rule.result for rule in rules}}
    path.write_text(yaml.safe_dump(payload, sort_keys=True, allow_unicode=True), encoding="utf-8")


def parse_rule_expression(expression: str) -> tuple[str, str]:
    match = re.fullmatch(r"\s*([A-Za-z_][A-Za-z0-9_]*)\((.*)\)\s*", expression)
    if match:
        return match.group(1), match.group(2).strip() or "*"
    if expression.strip():
        return expression.strip(), "*"
    raise PermissionError("Permission rule expression cannot be empty.")


def rule_matches(rule: PermissionRule, tool_name: str, target: str) -> bool:
    if rule.tool_name != tool_name and rule.tool_name != "*":
        return False
    return fnmatch.fnmatchcase(normalize_target(target), normalize_target(rule.pattern))


def tool_match_target(tool_call: Any) -> str:
    if tool_call.name == "Bash":
        return str(tool_call.arguments.get("command") or "")
    if tool_call.name in {"ReadFile", "WriteFile", "EditFile", "WritePlanFile"}:
        return str(tool_call.arguments.get("path") or "")
    if tool_call.name == "Glob":
        return str(tool_call.arguments.get("pattern") or "")
    if tool_call.name == "Grep":
        return str(tool_call.arguments.get("query") or "")
    return ""


def exact_rule_pattern(tool_call: Any) -> str:
    target = tool_match_target(tool_call).replace("\\", "/")
    return target or "*"


def path_argument(tool_call: Any) -> str | None:
    if tool_call.name in {"ReadFile", "WriteFile", "EditFile", "WritePlanFile"}:
        return str(tool_call.arguments.get("path") or "")
    return None


def normalize_target(value: str) -> str:
    return value.replace("\\", "/")
