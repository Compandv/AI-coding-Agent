from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from mewcode.prompts import system_reminder_message
from mewcode.session import Message
from mewcode.tools import ToolRegistry


SkillMode = Literal["inline", "fork"]
SkillHistory = Literal["none", "recent", "full"]
SkillSource = Literal["builtin", "user", "project"]

DEFAULT_SYSTEM_TOOLS = frozenset(
    {
        "ListSkills",
        "LoadSkill",
        "ActivateSkill",
        "ListMCPServers",
        "ActivateMCPServer",
    }
)
VALID_MODES = {"inline", "fork"}
VALID_HISTORY = {"none", "recent", "full"}
REFERENCE_SUFFIXES = {".md", ".markdown", ".txt"}


class SkillParseError(ValueError):
    """Raised when one Skill file cannot be parsed or validated."""


@dataclass(frozen=True)
class SkillIssue:
    path: Path
    message: str
    source: SkillSource = "project"


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    description: str
    body: str
    allowed_tools: tuple[str, ...] = ()
    mode: SkillMode = "inline"
    history: SkillHistory = "recent"
    model: str = ""
    source: SkillSource = "builtin"
    source_path: Path | None = None
    references: dict[str, str] = field(default_factory=dict)
    tool_metadata: dict[str, Any] = field(default_factory=dict)

    def render(self, arguments: str = "") -> str:
        return self.body.replace("$ARGUMENTS", arguments.strip())

    def summary_dict(self, active: bool = False) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "mode": self.mode,
            "history": self.history,
            "allowedTools": list(self.allowed_tools),
            "source": self.source,
            "source_path": str(self.source_path or ""),
            "active": active,
        }

    def full_dict(self, arguments: str = "") -> dict[str, Any]:
        return {
            **self.summary_dict(active=False),
            "instructions": self.render(arguments),
            "references": dict(self.references),
            "tool_metadata": dict(self.tool_metadata),
        }


class SkillManager:
    def __init__(
        self,
        project_root: Path,
        registry: ToolRegistry,
        *,
        user_home: Path | None = None,
        mcp_server_names: set[str] | None = None,
        builtin_dir: Path | None = None,
        system_tools: set[str] | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.registry = registry
        self.user_home = Path(user_home) if user_home is not None else Path.home()
        self.mcp_server_names = set(mcp_server_names or set())
        self.builtin_dir = builtin_dir or Path(__file__).parent / "builtin"
        self.system_tools = frozenset(system_tools or DEFAULT_SYSTEM_TOOLS)
        self.skills: dict[str, SkillDefinition] = {}
        self.issues: list[SkillIssue] = []
        self.active_skill_names: list[str] = []

    @property
    def project_skills_dir(self) -> Path:
        return self.project_root / ".mewcode" / "skills"

    @property
    def user_skills_dir(self) -> Path:
        return self.user_home / ".mewcode" / "skills"

    def load(self) -> None:
        self.skills = {}
        self.issues = []
        for source, directory in (
            ("builtin", self.builtin_dir),
            ("user", self.user_skills_dir),
            ("project", self.project_skills_dir),
        ):
            self._load_directory(directory, source)  # type: ignore[arg-type]
        self.active_skill_names = [name for name in self.active_skill_names if name in self.skills]

    def reload(self) -> None:
        previous_active = list(self.active_skill_names)
        self.load()
        self.active_skill_names = [name for name in previous_active if name in self.skills]

    def _load_directory(self, directory: Path, source: SkillSource) -> None:
        if not directory.exists():
            return
        if not directory.is_dir():
            self.issues.append(SkillIssue(directory, "Skill path is not a directory.", source))
            return
        candidates: list[Path] = []
        candidates.extend(sorted(path for path in directory.glob("*.md") if path.is_file()))
        candidates.extend(sorted(path / "SKILL.md" for path in directory.iterdir() if path.is_dir() and (path / "SKILL.md").exists()))
        for path in candidates:
            try:
                skill = parse_skill_file(path, source=source)
                self._validate_dependencies(skill)
            except SkillParseError as exc:
                self.issues.append(SkillIssue(path, str(exc), source))
                continue
            self.skills[skill.name] = skill

    def _validate_dependencies(self, skill: SkillDefinition) -> None:
        known_tools = set(self.registry.tools)
        for tool_name in skill.allowed_tools:
            if tool_name in known_tools or tool_name in self.system_tools:
                continue
            if "__" in tool_name:
                server_name, _, remote_name = tool_name.partition("__")
                if server_name in self.mcp_server_names and remote_name:
                    continue
            raise SkillParseError(f"Unknown allowed tool dependency: {tool_name}")

    def register_tools(self) -> None:
        from mewcode.skills.tools import ActivateSkillTool, ListSkillsTool, LoadSkillTool

        for tool in (ListSkillsTool(self), LoadSkillTool(self), ActivateSkillTool(self)):
            if tool.definition.name not in self.registry.tools:
                self.registry.register(tool)

    def list_skills(self) -> list[SkillDefinition]:
        return [self.skills[name] for name in sorted(self.skills)]

    def get(self, name: str) -> SkillDefinition | None:
        return self.skills.get(normalize_skill_name(name))

    def require(self, name: str) -> SkillDefinition:
        skill = self.get(name)
        if skill is None:
            raise SkillParseError(f"Unknown skill: {name}")
        return skill

    def activate(self, name: str) -> SkillDefinition:
        skill = self.require(name)
        if skill.name not in self.active_skill_names:
            self.active_skill_names.append(skill.name)
        return skill

    def clear_active(self) -> None:
        self.active_skill_names.clear()

    def active_skills(self) -> list[SkillDefinition]:
        return [self.skills[name] for name in self.active_skill_names if name in self.skills]

    def overlay_messages(self, turn_skill_names: list[str] | None = None, arguments: str = "") -> list[Message]:
        messages: list[Message] = []
        if self.skills:
            messages.append(system_reminder_message(self._skill_summary_overlay()))

        full_sections: list[str] = []
        for skill in self.active_skills():
            full_sections.append(self._full_skill_overlay(skill, reason="active", arguments=""))
        for name in turn_skill_names or []:
            skill = self.get(name)
            if skill is not None:
                full_sections.append(self._full_skill_overlay(skill, reason="current-turn", arguments=arguments))
        if full_sections:
            messages.append(system_reminder_message("\n\n".join(full_sections)))
        return messages

    def _skill_summary_overlay(self) -> str:
        lines = [
            "Available MewCode skills. Load a skill when a user request matches one of these reusable workflows.",
        ]
        for skill in self.list_skills():
            lines.append(f"- {skill.name}: {skill.description} (mode: {skill.mode}, source: {skill.source})")
        lines.append("Use LoadSkill for full SOP details, and ActivateSkill when the skill should persist across turns.")
        return "\n".join(lines)

    def _full_skill_overlay(self, skill: SkillDefinition, *, reason: str, arguments: str = "") -> str:
        lines = [
            f"Active skill ({reason}): {skill.name}",
            f"Description: {skill.description}",
            f"Mode: {skill.mode}",
            f"Allowed tools: {', '.join(skill.allowed_tools) if skill.allowed_tools else '(no extra tools)'}",
            "Instructions:",
            skill.render(arguments),
        ]
        if skill.references:
            lines.append("References:")
            for ref_name, content in skill.references.items():
                lines.append(f"- {ref_name}: {content[:1000]}")
        return "\n".join(lines).strip()

    def allowed_tool_patterns(self, turn_skill_names: list[str] | None = None) -> set[str] | None:
        names = list(self.active_skill_names)
        names.extend(turn_skill_names or [])
        names = [name for index, name in enumerate(names) if name in self.skills and name not in names[:index]]
        if not names:
            return None
        patterns = set(self.system_tools)
        for name in names:
            patterns.update(self.skills[name].allowed_tools)
        return patterns

    def tool_allowed(self, tool_name: str, turn_skill_names: list[str] | None = None) -> bool:
        patterns = self.allowed_tool_patterns(turn_skill_names)
        if patterns is None:
            return True
        return tool_name_matches_patterns(tool_name, patterns)

    def filter_tool_definitions(
        self,
        definitions: list[dict[str, Any]],
        turn_skill_names: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        patterns = self.allowed_tool_patterns(turn_skill_names)
        if patterns is None:
            return definitions
        return [definition for definition in definitions if tool_name_matches_patterns(str(definition.get("name") or ""), patterns)]

    def command_text(self, command_line: str) -> str:
        token, _, rest = command_line.strip().partition(" ")
        subcommand = rest.strip() if token.lower() == "/skill" else command_line.strip().removeprefix("/skill").strip()
        action, _, args = subcommand.partition(" ")
        action = action.lower().strip()
        args = args.strip()
        if action in {"", "list"}:
            return self._command_list()
        if action == "info":
            return self._command_info(args)
        if action == "reload":
            self.reload()
            return self._command_reload()
        return "Usage: /skill <list|info <name>|reload>"

    def _command_list(self) -> str:
        lines = ["Available skills:"]
        for skill in self.list_skills():
            active = " active" if skill.name in self.active_skill_names else ""
            lines.append(f"- {skill.name}: {skill.description} ({skill.mode}, {skill.source}{active})")
        if self.issues:
            lines.append("")
            lines.append(f"Warnings: {len(self.issues)} skill issue(s). Use /skill reload after fixing files.")
        return "\n".join(lines)

    def _command_info(self, name: str) -> str:
        if not name:
            return "Usage: /skill info <name>"
        skill = self.get(name)
        if skill is None:
            return f"Unknown skill: {name}"
        lines = [
            f"Skill: {skill.name}",
            f"- description: {skill.description}",
            f"- mode: {skill.mode}",
            f"- history: {skill.history}",
            f"- source: {skill.source}",
            f"- source path: {skill.source_path}",
            f"- allowed tools: {', '.join(skill.allowed_tools) if skill.allowed_tools else '(none)'}",
        ]
        if skill.references:
            lines.append(f"- references: {', '.join(sorted(skill.references))}")
        if skill.tool_metadata:
            lines.append("- tool metadata: present")
        return "\n".join(lines)

    def _command_reload(self) -> str:
        lines = [f"Reloaded {len(self.skills)} skill(s)."]
        if self.issues:
            lines.append("Warnings:")
            for issue in self.issues:
                lines.append(f"- {issue.source}: {issue.path}: {issue.message}")
        return "\n".join(lines)


def normalize_skill_name(name: str) -> str:
    return name.strip().lower().replace(" ", "-")


def parse_skill_file(path: Path, source: SkillSource = "project") -> SkillDefinition:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SkillParseError(f"Failed to read skill: {exc}") from exc
    metadata, body = split_frontmatter(text)
    raw_name = str(metadata.get("name") or "").strip()
    raw_description = str(metadata.get("description") or "").strip()
    if not raw_name:
        raise SkillParseError("Skill frontmatter must include name.")
    if not raw_description:
        raise SkillParseError("Skill frontmatter must include description.")
    name = normalize_skill_name(raw_name)
    allowed_tools = parse_allowed_tools(metadata.get("allowedTools", metadata.get("allowed_tools", [])))
    mode = str(metadata.get("mode") or "inline").strip().lower()
    if mode not in VALID_MODES:
        raise SkillParseError("Skill mode must be inline or fork.")
    history = str(metadata.get("history") or "recent").strip().lower()
    if history not in VALID_HISTORY:
        raise SkillParseError("Skill history must be none, recent, or full.")
    references, tool_metadata = read_directory_skill_extras(path)
    return SkillDefinition(
        name=name,
        description=raw_description,
        body=body.strip(),
        allowed_tools=tuple(allowed_tools),
        mode=mode,  # type: ignore[arg-type]
        history=history,  # type: ignore[arg-type]
        model=str(metadata.get("model") or "").strip(),
        source=source,
        source_path=path,
        references=references,
        tool_metadata=tool_metadata,
    )


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        raise SkillParseError("Skill file must start with YAML frontmatter.")
    lines = text.splitlines()
    closing_index: int | None = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = index
            break
    if closing_index is None:
        raise SkillParseError("Skill frontmatter is missing closing delimiter.")
    raw_frontmatter = "\n".join(lines[1:closing_index])
    body = "\n".join(lines[closing_index + 1 :])
    try:
        metadata = yaml.safe_load(raw_frontmatter) or {}
    except yaml.YAMLError as exc:
        raise SkillParseError(f"Failed to parse frontmatter: {exc}") from exc
    if not isinstance(metadata, dict):
        raise SkillParseError("Skill frontmatter must be a YAML mapping.")
    return metadata, body


def parse_allowed_tools(raw: Any) -> list[str]:
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise SkillParseError("allowedTools must be a list of tool names.")
    tools: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise SkillParseError("allowedTools must contain non-empty strings.")
        tools.append(item.strip())
    return tools


def read_directory_skill_extras(path: Path) -> tuple[dict[str, str], dict[str, Any]]:
    if path.name != "SKILL.md":
        return {}, {}
    root = path.parent
    references_dir = root / "references"
    references: dict[str, str] = {}
    if references_dir.exists() and references_dir.is_dir():
        for ref_path in sorted(item for item in references_dir.rglob("*") if item.is_file()):
            if ref_path.suffix.lower() not in REFERENCE_SUFFIXES:
                continue
            try:
                relative = ref_path.relative_to(references_dir).as_posix()
                references[relative] = ref_path.read_text(encoding="utf-8")
            except OSError:
                continue

    tool_metadata: dict[str, Any] = {}
    tool_json = root / "tool.json"
    if tool_json.exists():
        try:
            raw_metadata = json.loads(tool_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SkillParseError(f"Failed to parse tool.json: {exc}") from exc
        if not isinstance(raw_metadata, dict):
            raise SkillParseError("tool.json must contain a JSON object.")
        tool_metadata = raw_metadata
    return references, tool_metadata


def tool_name_matches_patterns(tool_name: str, patterns: set[str]) -> bool:
    if tool_name in patterns:
        return True
    for pattern in patterns:
        if pattern.endswith("__*") and tool_name.startswith(pattern[:-1]):
            return True
    return False
