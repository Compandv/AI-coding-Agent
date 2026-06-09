from __future__ import annotations

import json
from typing import Any

from .const import ESTIMATE_CHARS_PER_TOKEN, RECOVERY_FILE_LIMIT, RECOVERY_TOKENS_PER_FILE
from .state import FileReadRecord

BOUNDARY_NOTICE = (
    "需要文件原文、错误原文、命令输出原文或用户原话时，请使用读取/搜索工具重新读取对应路径；"
    "不要依据摘要或预览内容猜测精确代码。"
)


def render_file_block(record: FileReadRecord) -> str:
    char_limit = int(RECOVERY_TOKENS_PER_FILE * ESTIMATE_CHARS_PER_TOKEN)
    content = record.content
    if len(content) > char_limit:
        content = content[:char_limit].rstrip() + "\n(content truncated)"
    return f"### {record.path}\n[read at] {record.timestamp.isoformat()}\n{content}\n"


def render_tools_block(tool_definitions: list[dict[str, Any]]) -> str:
    if not tool_definitions:
        return "(无)"
    lines: list[str] = []
    for tool in tool_definitions:
        name = str(tool.get("name") or "")
        description = str(tool.get("description") or "")
        schema = tool.get("input_schema") or tool.get("parameters") or {}
        schema_text = json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        lines.append(f"- {name}: {description}\n  schema: {schema_text}")
    return "\n".join(lines)


def build_recovery_attachment(
    snapshots: list[FileReadRecord],
    tool_definitions: list[dict[str, Any]],
) -> str:
    files = snapshots[:RECOVERY_FILE_LIMIT]
    file_text = "\n".join(render_file_block(record).rstrip() for record in files) if files else "(无)"
    return (
        "## 最近读过的文件\n"
        f"{file_text}\n\n"
        "## 当前可用工具\n"
        f"{render_tools_block(tool_definitions)}\n\n"
        "## 边界提示\n"
        f"{BOUNDARY_NOTICE}"
    )
