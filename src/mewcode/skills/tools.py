from __future__ import annotations

from typing import Any

from mewcode.tools import Tool, ToolContext, ToolDefinition, ToolParameter, ToolResult, ToolSchema


class ListSkillsTool(Tool):
    def __init__(self, manager) -> None:
        self.manager = manager

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="ListSkills",
            description="List available MewCode skills and whether they are currently active.",
            schema=ToolSchema(),
            requires_confirmation=False,
        )

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        skills = [
            skill.summary_dict(active=skill.name in self.manager.active_skill_names)
            for skill in self.manager.list_skills()
        ]
        lines = ["Available skills:"]
        for skill in skills:
            active = " active" if skill["active"] else ""
            lines.append(f"- {skill['name']}: {skill['description']} ({skill['mode']}, {skill['source']}{active})")
        return ToolResult(ok=True, content="\n".join(lines), metadata={"skills": skills})


class LoadSkillTool(Tool):
    def __init__(self, manager) -> None:
        self.manager = manager

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="LoadSkill",
            description=(
                "Load the full SOP for a named MewCode skill. Use this when the user's request matches a skill "
                "summary and you need the complete instructions before acting."
            ),
            schema=ToolSchema(
                properties={
                    "name": ToolParameter(type="string", description="Skill name to load."),
                    "arguments": ToolParameter(type="string", description="Optional user arguments for $ARGUMENTS."),
                },
                required=["name"],
            ),
            requires_confirmation=False,
        )

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        name = str(arguments.get("name") or "")
        skill = self.manager.get(name)
        if skill is None:
            return ToolResult(ok=False, content="", error=f"Unknown skill: {name}", metadata={"tool_name": "LoadSkill"})
        rendered = skill.render(str(arguments.get("arguments") or ""))
        payload = skill.full_dict(arguments=str(arguments.get("arguments") or ""))
        return ToolResult(
            ok=True,
            content=rendered,
            metadata={"skill": payload, "allowedTools": list(skill.allowed_tools)},
        )


class ActivateSkillTool(Tool):
    def __init__(self, manager) -> None:
        self.manager = manager

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="ActivateSkill",
            description=(
                "Persistently activate a MewCode skill so its full SOP is injected into future turns. "
                "Use this when the current task should keep following the skill after this tool call."
            ),
            schema=ToolSchema(
                properties={
                    "name": ToolParameter(type="string", description="Skill name to activate."),
                },
                required=["name"],
            ),
            requires_confirmation=False,
        )

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        name = str(arguments.get("name") or "")
        skill = self.manager.get(name)
        if skill is None:
            return ToolResult(ok=False, content="", error=f"Unknown skill: {name}", metadata={"tool_name": "ActivateSkill"})
        self.manager.activate(skill.name)
        return ToolResult(
            ok=True,
            content=f"Activated skill: {skill.name}",
            metadata={
                "activated_skill": skill.name,
                "active_skills": list(self.manager.active_skill_names),
                "allowedTools": list(skill.allowed_tools),
            },
        )
