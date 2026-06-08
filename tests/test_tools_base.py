from pathlib import Path

import pytest

from mewcode.tools.base import ToolDefinition, ToolParameter, ToolResult, ToolSchema
from mewcode.tools.context import ToolContext


def test_tool_schema_converts_to_model_dict():
    schema = ToolSchema(
        properties={"path": ToolParameter(type="string", description="Target path.")},
        required=["path"],
    )

    assert schema.to_model_dict() == {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Target path."}},
        "required": ["path"],
    }


def test_tool_definition_includes_input_schema():
    definition = ToolDefinition(
        name="ReadFile",
        description="Read a file.",
        schema=ToolSchema(
            properties={"path": ToolParameter(type="string", description="Target path.")},
            required=["path"],
        ),
    )

    assert definition.to_model_dict()["name"] == "ReadFile"
    assert "input_schema" in definition.to_model_dict()


def test_tool_schema_can_pass_through_raw_json_schema():
    schema = ToolSchema.from_raw(
        {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Search query."}},
            "required": ["query"],
            "additionalProperties": False,
        }
    )

    assert schema.required == ["query"]
    assert schema.to_model_dict()["additionalProperties"] is False
    assert schema.to_model_dict()["properties"]["query"]["description"] == "Search query."


def test_tool_result_keeps_error_and_metadata():
    result = ToolResult(ok=False, content="", error="boom", metadata={"path": "a.txt"})

    assert result.to_message_content() == {
        "ok": False,
        "content": "",
        "error": "boom",
        "metadata": {"path": "a.txt"},
    }
