from datetime import datetime, timezone

from mewcode.prompts import (
    BehaviorSection,
    CodeQualitySection,
    IdentitySection,
    OutputStyleSection,
    SecuritySection,
    TaskPatternSection,
    ToolUsageSection,
    assemble_api_payload,
    assemble_system_prompt,
    default_system_sections,
    environment_context_message,
    plan_mode_reminder,
    system_reminder_message,
)


def test_system_prompt_contains_seven_stable_sections():
    sections = default_system_sections()

    assert [type(section) for section in sections] == [
        IdentitySection,
        BehaviorSection,
        ToolUsageSection,
        CodeQualitySection,
        SecuritySection,
        TaskPatternSection,
        OutputStyleSection,
    ]
    assert all(section.name and section.content and isinstance(section.priority, int) for section in sections)
    assert assemble_system_prompt(sections) == assemble_system_prompt(sections)


def test_system_prompt_sorts_sections_by_priority():
    sections = [OutputStyleSection(), IdentitySection(), BehaviorSection()]
    rendered = assemble_system_prompt(sections)

    assert rendered.index("## Identity") < rendered.index("## Behavior") < rendered.index("## Output Style")


def test_tool_usage_prompt_prefers_readfile_metadata_and_windows_safe_shell():
    rendered = assemble_system_prompt([ToolUsageSection()])

    assert "request multiple ReadFile tool calls in the same model response" in rendered
    assert "Use ReadFile start_line/end_line for snippets or line ranges" in rendered
    assert "After read tools, use metadata" in rendered
    assert "Do not run Bash only to count or slice files already read" in rendered
    assert "avoid POSIX heredocs" in rendered


def test_system_reminder_uses_user_role_and_xml_wrapper():
    message = system_reminder_message("Stay read-only.")

    assert message["role"] == "user"
    assert message["content"].startswith("<system-reminder>")
    assert message["content"].endswith("</system-reminder>")


def test_environment_context_is_a_request_overlay_message(tmp_path):
    message = environment_context_message(tmp_path, now=datetime(2026, 6, 6, tzinfo=timezone.utc))

    assert message["role"] == "user"
    assert "<system-reminder>" in message["content"]
    assert "Working directory:" in message["content"]
    assert "Platform:" in message["content"]
    assert "Current time: 2026-06-06T00:00:00+00:00" in message["content"]
    assert "Git:" in message["content"]


def test_assemble_api_payload_distributes_seven_sources_to_three_channels(tmp_path):
    session_messages = [{"role": "user", "content": "hello"}]
    tools = [{"name": "ReadFile", "description": "Read", "input_schema": {"type": "object"}}]

    payload = assemble_api_payload(
        session_messages=session_messages,
        tools=tools,
        root_dir=tmp_path,
        mode="normal",
        model_request_index=1,
        now=datetime(2026, 6, 6, tzinfo=timezone.utc),
    )

    assert "## Identity" in payload.system
    assert payload.tools == tools
    assert payload.messages[0]["content"].startswith("<system-reminder>")
    assert payload.messages[1] == {"role": "user", "content": "hello"}
    assert session_messages == [{"role": "user", "content": "hello"}]


def test_plan_mode_reminder_uses_full_on_first_and_every_fifth_request():
    first = plan_mode_reminder(1)["content"]
    second = plan_mode_reminder(2)["content"]
    fifth = plan_mode_reminder(5)["content"]

    assert "Full Plan Mode guidance" in first
    assert "By default, produce the plan in chat" in first
    assert "Plan Mode is active" in second
    assert "Full Plan Mode guidance" in fifth


def test_plan_payload_adds_plan_reminder_as_overlay(tmp_path):
    payload = assemble_api_payload(
        session_messages=[{"role": "user", "content": "plan something"}],
        tools=[],
        root_dir=tmp_path,
        mode="plan",
        model_request_index=5,
    )

    assert payload.metadata["plan_reminder"] == "full"
    assert payload.messages[-1]["role"] == "user"
    assert "Full Plan Mode guidance" in payload.messages[-1]["content"]
