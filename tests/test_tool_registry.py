import pytest

from mewcode.tools.base import ToolError
from mewcode.tools.registry import default_registry


def test_default_registry_exposes_chapter_four_tools():
    registry = default_registry()

    assert set(registry.tools) == {
        "ReadFile",
        "WriteFile",
        "EditFile",
        "Bash",
        "Glob",
        "Grep",
        "AskUserQuestion",
        "WritePlanFile",
    }
    assert len(registry.list_definitions()) == 8


def test_registry_prompts_glob_and_grep_more_explicitly():
    registry = default_registry()
    definitions = {definition["name"]: definition for definition in registry.list_definitions()}

    assert "entry files" in definitions["Glob"]["description"]
    assert "**/main.py" in definitions["Glob"]["description"]
    assert "Prefer Glob over Bash" in definitions["Glob"]["description"]
    assert "Required. A glob pattern" in definitions["Glob"]["input_schema"]["properties"]["pattern"]["description"]
    assert "symbol" in definitions["Grep"]["description"]
    assert "then use ReadFile" in definitions["Grep"]["description"]
    assert "Prefer Grep over Bash" in definitions["Grep"]["description"]
    assert "Required. Text to search for inside files." in definitions["Grep"]["input_schema"]["properties"]["query"]["description"]
    assert "before EditFile" in definitions["ReadFile"]["description"]
    assert "Read the target file first" in definitions["EditFile"]["description"]
    assert "Create or overwrite" in definitions["WriteFile"]["description"]
    assert "Prefer Glob, Grep, ReadFile, WriteFile, and EditFile" in definitions["Bash"]["description"]


def test_registry_ask_user_question_options_support_custom_other():
    registry = default_registry()
    definitions = {definition["name"]: definition for definition in registry.list_definitions()}
    ask_schema = definitions["AskUserQuestion"]["input_schema"]

    option_variants = ask_schema["properties"]["options"]["items"]["anyOf"]
    option_object = next(item for item in option_variants if item["type"] == "object")
    assert option_object["properties"]["allow_custom_input"]["type"] == "boolean"

    nested_option = ask_schema["properties"]["questions"]["items"]["properties"]["options"]["items"]
    assert nested_option["properties"]["allow_custom_input"]["type"] == "boolean"


def test_registry_rejects_unknown_tool():
    registry = default_registry()

    with pytest.raises(ToolError):
        registry.get("Unknown")
