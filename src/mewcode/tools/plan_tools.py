from __future__ import annotations

from typing import Any

from .base import Tool, ToolDefinition, ToolError, ToolParameter, ToolResult, ToolSchema
from .context import ToolContext


class AskUserQuestionTool(Tool):
    definition = ToolDefinition(
        name="AskUserQuestion",
        description=(
            "Ask the user one concise clarification question when the request is too broad or ambiguous. "
            "Use this in Plan Mode before writing a large plan. Provide 2-4 short options when helpful. "
            "Use an Other option with allow_custom_input when the user may need to type a custom answer."
        ),
        schema=ToolSchema(
            properties={
                "question": ToolParameter(type="string", description="The clarification question to ask the user."),
                "options": ToolParameter(
                    type="array",
                    description=(
                        "Optional short answer choices. Keep each choice brief and mutually exclusive. "
                        "Each option may be a string or an object with label, description, recommended, "
                        "and allow_custom_input."
                    ),
                    items={
                        "anyOf": [
                            {"type": "string"},
                            {
                                "type": "object",
                                "properties": {
                                    "label": {"type": "string"},
                                    "description": {"type": "string"},
                                    "recommended": {"type": "boolean"},
                                    "allow_custom_input": {"type": "boolean"},
                                },
                                "required": ["label"],
                            },
                        ]
                    },
                ),
                "reason": ToolParameter(type="string", description="Why this question is needed before planning."),
                "questions": ToolParameter(
                    type="array",
                    description=(
                        "Optional list of multiple clarification questions. Each item should include id, title, "
                        "question, and options. Each option may include label, description, recommended, "
                        "and allow_custom_input."
                    ),
                    items={
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "title": {"type": "string"},
                            "question": {"type": "string"},
                            "options": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "label": {"type": "string"},
                                        "description": {"type": "string"},
                                        "recommended": {"type": "boolean"},
                                        "allow_custom_input": {"type": "boolean"},
                                    },
                                    "required": ["label"],
                                },
                            },
                        },
                        "required": ["question"],
                    },
                ),
            },
            required=[],
        ),
    )

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        _ = context
        questions = self._normalize_questions(arguments)
        if not questions:
            raise ToolError("AskUserQuestion requires either question or questions.")

        first = questions[0]
        content_parts: list[str] = []
        for index, question in enumerate(questions, start=1):
            title = question["title"]
            prompt = question["question"]
            content_parts.append(f"{index}. {title}: {prompt}")
            options = question.get("options") or []
            for option in options:
                label = option["label"]
                markers = []
                if option.get("recommended"):
                    markers.append("recommended")
                if option.get("allow_custom_input"):
                    markers.append("custom")
                marker = f" ({', '.join(markers)})" if markers else ""
                description = option.get("description") or ""
                suffix = f" - {description}" if description else ""
                content_parts.append(f"   - {label}{marker}{suffix}")
        return ToolResult(
            ok=True,
            content="\n".join(content_parts),
            metadata={
                "await_user": True,
                "question": first["question"],
                "options": [option["label"] for option in first.get("options", [])],
                "questions": questions,
                "reason": str(arguments.get("reason") or ""),
            },
        )

    def _normalize_questions(self, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        raw_questions = arguments.get("questions")
        if isinstance(raw_questions, list) and raw_questions:
            questions = [self._normalize_question(item, index) for index, item in enumerate(raw_questions, start=1)]
            return [question for question in questions if question["question"]]

        question = str(arguments.get("question") or "").strip()
        if not question:
            return []
        options = self._normalize_options(arguments.get("options") or [])
        return [
            {
                "id": "question_1",
                "title": "Question 1",
                "question": question,
                "options": options,
            }
        ]

    def _normalize_question(self, raw_question: Any, index: int) -> dict[str, Any]:
        if not isinstance(raw_question, dict):
            prompt = str(raw_question).strip()
            return {
                "id": f"question_{index}",
                "title": f"Question {index}",
                "question": prompt,
                "options": [],
            }
        prompt = str(raw_question.get("question") or "").strip()
        title = str(raw_question.get("title") or raw_question.get("id") or f"Question {index}").strip()
        question_id = str(raw_question.get("id") or f"question_{index}").strip()
        return {
            "id": question_id or f"question_{index}",
            "title": title or f"Question {index}",
            "question": prompt,
            "options": self._normalize_options(raw_question.get("options") or []),
        }

    def _normalize_options(self, raw_options: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_options, list):
            return []
        options: list[dict[str, Any]] = []
        for raw_option in raw_options:
            if isinstance(raw_option, dict):
                label = str(raw_option.get("label") or "").strip()
                if not label:
                    continue
                options.append(
                    {
                        "label": label,
                        "description": str(raw_option.get("description") or "").strip(),
                        "recommended": bool(raw_option.get("recommended")),
                        "allow_custom_input": bool(raw_option.get("allow_custom_input")),
                    }
                )
            else:
                label = str(raw_option).strip()
                if label:
                    options.append(
                        {
                            "label": label,
                            "description": "",
                            "recommended": False,
                            "allow_custom_input": False,
                        }
                    )
        return options


class WritePlanFileTool(Tool):
    definition = ToolDefinition(
        name="WritePlanFile",
        description=(
            "Write or replace a Markdown implementation plan during Plan Mode. "
            "Only use this for plan documents, not source code changes."
        ),
        schema=ToolSchema(
            properties={
                "path": ToolParameter(
                    type="string",
                    description="Markdown plan path under plans/ or docs/plans/, such as plans/deep-plan.md.",
                ),
                "content": ToolParameter(type="string", description="Full Markdown plan content."),
            },
            required=["path", "content"],
        ),
    )

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        raw_path = str(arguments["path"])
        if not raw_path.endswith(".md"):
            raise ToolError("Plan file path must end with .md.")
        path = context.resolve_path(raw_path)
        relative = path.relative_to(context.root_dir.resolve()).as_posix()
        if not (relative.startswith("plans/") or relative.startswith("docs/plans/")):
            raise ToolError("Plan files must be written under plans/ or docs/plans/.")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(arguments["content"]), encoding="utf-8")
        except OSError as exc:
            raise ToolError(f"Failed to write plan file: {exc}") from exc
        line_count = len(str(arguments["content"]).splitlines())
        return ToolResult(
            ok=True,
            content=f"Wrote plan file: {relative}",
            metadata={"path": str(path), "relative_path": relative, "line_count": line_count, "plan_file": True},
        )
