from mewcode.agent import (
    DEFAULT_MAX_TOOL_STEPS,
    ConfirmationRequired,
    ContextCompressionFinished,
    ContextCompressionStarted,
    ContextEmergencyRetry,
    ContextStatsReported,
    PendingToolRequest,
    SingleToolAgent,
    ToolFinished,
    ToolResultSpilled,
    UserQuestionRequested,
)
from mewcode.context import ContextConfig, ContextManager
from mewcode.permissions import PermissionChecker
from mewcode.providers.base import ChatResponse, StreamChunk, ToolCall
from mewcode.providers.errors import ProviderError
from mewcode.session import ChatSession
from mewcode.tools.base import Tool, ToolDefinition, ToolSchema
from mewcode.tools.context import ToolContext
from mewcode.tools.registry import ToolRegistry, default_registry
from mewcode.mcp.client import MCPClient, MCPTool
from mewcode.mcp.jsonrpc import make_success_response
from mewcode.mcp.tools import MCPToolWrapper


class FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete_chat(self, messages, tools=None):
        self.calls.append({"messages": messages, "tools": tools})
        return self.responses.pop(0)


class NoStreamProvider(FakeProvider):
    def stream_chat(self, messages):
        yield from ()


class FailingStreamProvider(FakeProvider):
    def __init__(self, responses):
        super().__init__(responses)
        self.stream_calls = []

    def stream_response(self, messages, tools=None):
        self.stream_calls.append({"messages": messages, "tools": tools})
        raise ProviderError("Streaming response failed: peer closed connection without sending complete message body")
        yield  # pragma: no cover


class PartialThenFailingStreamProvider(FakeProvider):
    def __init__(self):
        super().__init__([ChatResponse(text="fallback should not run")])
        self.stream_calls = []

    def stream_response(self, messages, tools=None):
        self.stream_calls.append({"messages": messages, "tools": tools})
        yield StreamChunk(text="partial")
        raise ProviderError("Streaming response failed: peer closed connection without sending complete message body")


class ScriptedTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []

    def send(self, message):
        self.sent.append(message)

    def receive(self, timeout_seconds=None):
        return self.responses.pop(0)

    def close(self):
        pass


class ExplodingTool(Tool):
    definition = ToolDefinition(name="Explode", description="Explode", schema=ToolSchema())

    def execute(self, arguments, context):
        raise TypeError("boom")


def test_agent_returns_direct_answer_without_tool(tmp_path):
    provider = NoStreamProvider([ChatResponse(text="hello")])
    agent = SingleToolAgent(provider=provider, registry=default_registry(), context=ToolContext(root_dir=tmp_path))
    session = ChatSession()

    result = agent.run_turn(session, "hi")

    assert result.final_text == "hello"
    assert result.tool_calls == []
    assert result.stop_reason == "final"
    assert session.messages == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


def test_agent_falls_back_to_non_streaming_when_stream_closes_before_content(tmp_path):
    provider = FailingStreamProvider([ChatResponse(text="我是 MewCode。")])
    agent = SingleToolAgent(provider=provider, registry=default_registry(), context=ToolContext(root_dir=tmp_path))
    session = ChatSession()

    result = agent.run_turn(session, "你是谁")

    assert result.final_text == "我是 MewCode。"
    assert result.stop_reason == "final"
    assert len(provider.stream_calls) == 1
    assert len(provider.calls) == 1


def test_agent_does_not_fallback_after_partial_stream_content(tmp_path):
    provider = PartialThenFailingStreamProvider()
    agent = SingleToolAgent(provider=provider, registry=default_registry(), context=ToolContext(root_dir=tmp_path))
    session = ChatSession()

    events = list(agent.stream_turn(session, "hi"))

    assert any(getattr(event, "text", "") == "partial" for event in events)
    assert any(getattr(event, "message", "") == "Streaming response failed: peer closed connection without sending complete message body" for event in events)
    assert provider.calls == []


def test_agent_returns_tool_failure_when_tool_raises_unexpected_exception(tmp_path):
    provider = NoStreamProvider(
        [
            ChatResponse(text="", tool_call=ToolCall(name="Explode", arguments={})),
            ChatResponse(text="Recovered."),
        ]
    )
    registry = ToolRegistry({"Explode": ExplodingTool()})
    agent = SingleToolAgent(provider=provider, registry=registry, context=ToolContext(root_dir=tmp_path))
    session = ChatSession()

    result = agent.run_turn(session, "run exploding tool")

    assert result.tool_result["ok"] is False
    assert result.tool_result["metadata"]["unexpected_tool_error"] is True
    assert "boom" in result.tool_result["error"]
    assert result.final_text == "Recovered."


def test_agent_loops_across_multiple_tool_steps_before_final_answer(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("project", encoding="utf-8")
    provider = NoStreamProvider(
        [
            ChatResponse(text="", tool_call=ToolCall(name="Glob", arguments={"pattern": "*.md"})),
            ChatResponse(text="", tool_call=ToolCall(name="ReadFile", arguments={"path": "README.md"})),
            ChatResponse(text="I found the project file."),
        ]
    )
    agent = SingleToolAgent(provider=provider, registry=default_registry(), context=ToolContext(root_dir=tmp_path))
    session = ChatSession()

    result = agent.run_turn(session, "find and read the readme")

    assert [tool_call.name for tool_call in result.tool_calls] == ["Glob", "ReadFile"]
    assert [tool_result["ok"] for tool_result in result.tool_results] == [True, True]
    assert result.final_text == "I found the project file."
    assert all(call["tools"] is not None for call in provider.calls)
    assert [message["role"] for message in session.messages] == [
        "user",
        "assistant",
        "tool",
        "assistant",
        "tool",
        "assistant",
    ]


def test_agent_executes_multiple_tool_calls_from_one_model_response_and_preserves_result_order(tmp_path):
    (tmp_path / "a.txt").write_text("A", encoding="utf-8")
    (tmp_path / "b.txt").write_text("B", encoding="utf-8")
    provider = NoStreamProvider(
        [
            ChatResponse(
                text="",
                tool_calls=[
                    ToolCall(name="ReadFile", arguments={"path": "a.txt"}, id="read_a"),
                    ToolCall(name="ReadFile", arguments={"path": "b.txt"}, id="read_b"),
                ],
            ),
            ChatResponse(text="Read both files."),
        ]
    )
    agent = SingleToolAgent(provider=provider, registry=default_registry(), context=ToolContext(root_dir=tmp_path))
    session = ChatSession()

    result = agent.run_turn(session, "read both")

    assert [tool_call.id for tool_call in result.tool_calls] == ["read_a", "read_b"]
    assert [tool_result["content"] for tool_result in result.tool_results] == ["A", "B"]
    tool_result_messages = [message for message in session.messages if message["role"] == "tool"]
    assert [message["tool_id"] for message in tool_result_messages] == ["read_a", "read_b"]


def test_agent_preserves_result_order_for_mixed_tool_batch_without_provider_ids(tmp_path):
    (tmp_path / "existing.txt").write_text("old", encoding="utf-8")
    provider = NoStreamProvider(
        [
            ChatResponse(
                text="",
                tool_calls=[
                    ToolCall(name="WriteFile", arguments={"path": "created.txt", "content": "new"}),
                    ToolCall(name="ReadFile", arguments={"path": "existing.txt"}),
                ],
            ),
            ChatResponse(text="Done."),
        ]
    )
    agent = SingleToolAgent(provider=provider, registry=default_registry(), context=ToolContext(root_dir=tmp_path))
    session = ChatSession()

    result = agent.run_turn(session, "write and read")

    assert [tool_result["ok"] for tool_result in result.tool_results] == [True, True]
    assert "created.txt" in result.tool_results[0]["content"]
    assert result.tool_results[1]["content"] == "old"
    tool_result_messages = [message for message in session.messages if message["role"] == "tool"]
    assert [message["tool_id"] for message in tool_result_messages] == ["WriteFile_0", "ReadFile_1"]


def test_agent_executes_sensitive_tools_without_confirmation_in_normal_mode(tmp_path):
    provider = NoStreamProvider(
        [
            ChatResponse(text="", tool_call=ToolCall(name="WriteFile", arguments={"path": "note.txt", "content": "hi"})),
            ChatResponse(text="Created the file."),
        ]
    )
    agent = SingleToolAgent(provider=provider, registry=default_registry(), context=ToolContext(root_dir=tmp_path))
    session = ChatSession()

    result = agent.run_turn(session, "create note")

    assert result.needs_confirmation is False
    assert result.pending_request is None
    assert result.tool_result["ok"] is True
    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "hi"
    assert result.final_text == "Created the file."


def test_agent_requests_permission_confirmation_when_checker_asks(tmp_path):
    provider = NoStreamProvider(
        [ChatResponse(text="", tool_call=ToolCall(name="WriteFile", arguments={"path": "note.txt", "content": "hi"}))]
    )
    context = ToolContext(root_dir=tmp_path)
    checker = PermissionChecker.from_workspace(context, mode="default", user_path=tmp_path / "missing-user.yaml")
    agent = SingleToolAgent(provider=provider, registry=default_registry(), context=context, permission_checker=checker)
    session = ChatSession()

    events = list(agent.stream_turn(session, "create note"))

    confirmations = [event for event in events if isinstance(event, ConfirmationRequired)]
    assert len(confirmations) == 1
    assert confirmations[0].pending_request.tool_call.name == "WriteFile"
    assert events[-1].reason == "await_user"
    assert not (tmp_path / "note.txt").exists()


def test_agent_confirm_once_executes_pending_tool(tmp_path):
    provider = NoStreamProvider([ChatResponse(text="Created.")])
    context = ToolContext(root_dir=tmp_path)
    checker = PermissionChecker.from_workspace(context, mode="default", user_path=tmp_path / "missing-user.yaml")
    agent = SingleToolAgent(provider=provider, registry=default_registry(), context=context, permission_checker=checker)
    session = ChatSession()
    pending = PendingToolRequest(ToolCall(name="WriteFile", arguments={"path": "note.txt", "content": "hi"}))

    events = list(agent.stream_confirm(session, pending))

    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "hi"
    finished = [event for event in events if isinstance(event, ToolFinished)]
    assert finished[0].result["ok"] is True


def test_agent_denies_dangerous_command_and_lets_model_continue(tmp_path):
    provider = NoStreamProvider(
        [
            ChatResponse(text="", tool_call=ToolCall(name="Bash", arguments={"command": "rm -rf /"})),
            ChatResponse(text="I will avoid that command."),
        ]
    )
    context = ToolContext(root_dir=tmp_path)
    checker = PermissionChecker.from_workspace(context, mode="bypassPermissions", user_path=tmp_path / "missing-user.yaml")
    agent = SingleToolAgent(provider=provider, registry=default_registry(), context=context, permission_checker=checker)
    session = ChatSession()

    result = agent.run_turn(session, "clean temp files")

    assert result.tool_result["ok"] is False
    assert result.tool_result["metadata"]["blocked_by_dangerous_command"] is True
    assert result.final_text == "I will avoid that command."


def test_agent_denies_broad_env_read_and_lets_model_retry_exact_file(tmp_path):
    (tmp_path / ".env").write_text("TOKEN=ok", encoding="utf-8")
    provider = NoStreamProvider(
        [
            ChatResponse(text="", tool_call=ToolCall(name="ReadFile", arguments={"path": "*.env*"})),
            ChatResponse(text="", tool_call=ToolCall(name="ReadFile", arguments={"path": ".env"})),
            ChatResponse(text="Read the explicit env file."),
        ]
    )
    context = ToolContext(root_dir=tmp_path)
    checker = PermissionChecker.from_workspace(context, mode="bypassPermissions", user_path=tmp_path / "missing-user.yaml")
    agent = SingleToolAgent(provider=provider, registry=default_registry(), context=context, permission_checker=checker)
    session = ChatSession()

    result = agent.run_turn(session, "read env files")

    assert result.tool_results[0]["ok"] is False
    assert result.tool_results[0]["metadata"]["blocked_by_sensitive_read_pattern"] is True
    assert result.tool_results[0]["metadata"]["suggested_paths"][0] == ".env"
    assert result.tool_results[1]["ok"] is True
    assert result.tool_results[1]["content"] == "TOKEN=ok"
    assert result.final_text == "Read the explicit env file."


def test_agent_blocks_unsafe_tools_in_plan_mode_and_continues_to_final_plan(tmp_path):
    provider = NoStreamProvider(
        [
            ChatResponse(text="", tool_call=ToolCall(name="WriteFile", arguments={"path": "note.txt", "content": "hi"})),
            ChatResponse(text="Plan: create note.txt with hi after approval."),
        ]
    )
    agent = SingleToolAgent(provider=provider, registry=default_registry(), context=ToolContext(root_dir=tmp_path))
    session = ChatSession()

    result = agent.run_turn(session, "create note", mode="plan")

    assert result.tool_result["ok"] is False
    assert result.tool_result["metadata"]["blocked_by_plan_mode"] is True
    assert not (tmp_path / "note.txt").exists()
    assert result.final_text == "Plan: create note.txt with hi after approval."
    assert session.messages[0]["content"] == "create note"
    assert provider.calls[0]["messages"].system.startswith("## Identity")
    assert "Full Plan Mode guidance" in provider.calls[0]["messages"].messages[-1]["content"]


def test_agent_plan_mode_blocks_plan_file_by_default(tmp_path):
    provider = NoStreamProvider(
        [
            ChatResponse(
                text="",
                tool_calls=[
                    ToolCall(name="WritePlanFile", arguments={"path": "plans/shop.md", "content": "# Plan\n\nBuild MVP."}),
                    ToolCall(name="WriteFile", arguments={"path": "app.py", "content": "print('side effect')"}),
                ],
            ),
            ChatResponse(text="Plan file is ready. Please accept or adjust it."),
        ]
    )
    agent = SingleToolAgent(provider=provider, registry=default_registry(), context=ToolContext(root_dir=tmp_path))
    session = ChatSession()

    result = agent.run_turn(session, "plan a shop", mode="plan")

    assert not (tmp_path / "plans" / "shop.md").exists()
    assert not (tmp_path / "app.py").exists()
    assert [tool_result["ok"] for tool_result in result.tool_results] == [False, False]
    assert result.tool_results[0]["metadata"]["requires_explicit_plan_file"] is True
    assert result.tool_results[1]["metadata"]["blocked_by_plan_mode"] is True
    assert result.final_text == "Plan file is ready. Please accept or adjust it."


def test_agent_plan_mode_can_write_plan_file_when_user_explicitly_asks(tmp_path):
    provider = NoStreamProvider(
        [
            ChatResponse(
                text="",
                tool_call=ToolCall(name="WritePlanFile", arguments={"path": "plans/shop.md", "content": "# Plan"}),
            ),
            ChatResponse(text="Saved the plan file."),
        ]
    )
    agent = SingleToolAgent(provider=provider, registry=default_registry(), context=ToolContext(root_dir=tmp_path))
    session = ChatSession()

    result = agent.run_turn(session, "plan a shop and save the plan file", mode="plan")

    assert (tmp_path / "plans" / "shop.md").read_text(encoding="utf-8") == "# Plan"
    assert result.tool_result["metadata"]["plan_file"] is True
    assert result.final_text == "Saved the plan file."


def test_agent_plan_mode_ask_user_question_stops_for_clarification(tmp_path):
    provider = NoStreamProvider(
        [
            ChatResponse(
                text="",
                tool_call=ToolCall(
                    name="AskUserQuestion",
                    arguments={
                        "question": "Is this a new project or inside this repo?",
                        "options": ["New project", "Inside this repo"],
                        "reason": "Project scope changes the plan.",
                    },
                ),
            )
        ]
    )
    agent = SingleToolAgent(provider=provider, registry=default_registry(), context=ToolContext(root_dir=tmp_path))
    session = ChatSession()

    events = list(agent.stream_turn(session, "plan an ecommerce system", mode="plan"))

    questions = [event for event in events if isinstance(event, UserQuestionRequested)]
    assert len(questions) == 1
    assert questions[0].question == "Is this a new project or inside this repo?"
    assert questions[0].options == ["New project", "Inside this repo"]
    assert events[-1].reason == "await_user"


def test_agent_plan_mode_reminders_are_request_overlays_not_session_history(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("project", encoding="utf-8")
    provider = NoStreamProvider(
        [
            ChatResponse(text="", tool_call=ToolCall(name="Glob", arguments={"pattern": "*.md"})),
            ChatResponse(text="", tool_call=ToolCall(name="ReadFile", arguments={"path": "README.md"})),
            ChatResponse(text="Plan ready."),
        ]
    )
    agent = SingleToolAgent(provider=provider, registry=default_registry(), context=ToolContext(root_dir=tmp_path))
    session = ChatSession()

    result = agent.run_turn(session, "plan with context", mode="plan")

    assert result.final_text == "Plan ready."
    assert all("<system-reminder>" not in str(message.get("content", "")) for message in session.messages)
    assert "Full Plan Mode guidance" in provider.calls[0]["messages"].messages[-1]["content"]
    assert "Plan Mode is active" in provider.calls[1]["messages"].messages[-1]["content"]


def test_agent_plan_mode_repeats_full_reminder_on_fifth_model_request(tmp_path):
    provider = NoStreamProvider(
        [
            ChatResponse(text="", tool_call=ToolCall(name="Glob", arguments={})),
            ChatResponse(text="", tool_call=ToolCall(name="Glob", arguments={})),
            ChatResponse(text="", tool_call=ToolCall(name="Glob", arguments={})),
            ChatResponse(text="", tool_call=ToolCall(name="Glob", arguments={})),
            ChatResponse(text="Final plan."),
        ]
    )
    agent = SingleToolAgent(provider=provider, registry=default_registry(), context=ToolContext(root_dir=tmp_path))
    session = ChatSession()

    result = agent.run_turn(session, "plan something", mode="plan")

    assert result.final_text == "Final plan."
    assert "Full Plan Mode guidance" in provider.calls[0]["messages"].messages[-1]["content"]
    assert "Plan Mode is active" in provider.calls[1]["messages"].messages[-1]["content"]
    assert "Plan Mode is active" in provider.calls[3]["messages"].messages[-1]["content"]
    assert "Full Plan Mode guidance" in provider.calls[4]["messages"].messages[-1]["content"]


def test_agent_plan_mode_ask_user_question_parses_single_custom_option(tmp_path):
    provider = NoStreamProvider(
        [
            ChatResponse(
                text="",
                tool_call=ToolCall(
                    name="AskUserQuestion",
                    arguments={
                        "question": "Which stack should the plan target?",
                        "options": [
                            {"label": "Python + FastAPI", "description": "API-first backend."},
                            {
                                "label": "Other",
                                "description": "Type a stack manually.",
                                "allow_custom_input": True,
                            },
                        ],
                    },
                ),
            )
        ]
    )
    agent = SingleToolAgent(provider=provider, registry=default_registry(), context=ToolContext(root_dir=tmp_path))
    session = ChatSession()

    events = list(agent.stream_turn(session, "plan an ecommerce system", mode="plan"))

    questions = [event for event in events if isinstance(event, UserQuestionRequested)]
    assert len(questions) == 1
    assert questions[0].questions[0].options[1].label == "Other"
    assert questions[0].questions[0].options[1].allow_custom_input is True


def test_agent_plan_mode_ask_user_question_parses_multiple_structured_questions(tmp_path):
    provider = NoStreamProvider(
        [
            ChatResponse(
                text="",
                tool_call=ToolCall(
                    name="AskUserQuestion",
                    arguments={
                        "reason": "Large projects need a few choices before planning.",
                        "questions": [
                            {
                                "id": "project_scope",
                                "title": "Project scope",
                                "question": "Where should the ecommerce system live?",
                                "options": [
                                    {
                                        "label": "Inside current repo",
                                        "description": "Add modules under this MewCode project.",
                                        "recommended": True,
                                    },
                                    {
                                        "label": "New standalone project",
                                        "description": "Create a separate application directory.",
                                    },
                                ],
                            },
                            {
                                "id": "tech_stack",
                                "title": "Tech stack",
                                "question": "Which stack should the plan target?",
                                "options": [
                                    {"label": "Python + FastAPI", "description": "API-first backend."},
                                    {"label": "Go + SQLite", "description": "Small self-contained backend."},
                                    {
                                        "label": "Other",
                                        "description": "Type a stack manually.",
                                        "allow_custom_input": True,
                                    },
                                ],
                            },
                        ],
                    },
                ),
            )
        ]
    )
    agent = SingleToolAgent(provider=provider, registry=default_registry(), context=ToolContext(root_dir=tmp_path))
    session = ChatSession()

    events = list(agent.stream_turn(session, "plan an ecommerce system", mode="plan"))

    questions = [event for event in events if isinstance(event, UserQuestionRequested)]
    assert len(questions) == 1
    event = questions[0]
    assert event.reason == "Large projects need a few choices before planning."
    assert [question.id for question in event.questions] == ["project_scope", "tech_stack"]
    assert event.questions[0].title == "Project scope"
    assert event.questions[0].options[0].label == "Inside current repo"
    assert event.questions[0].options[0].description == "Add modules under this MewCode project."
    assert event.questions[0].options[0].recommended is True
    assert event.questions[1].options[1].label == "Go + SQLite"
    assert event.questions[1].options[2].label == "Other"
    assert event.questions[1].options[2].allow_custom_input is True
    assert events[-1].reason == "await_user"


def test_agent_stops_at_max_tool_steps_without_executing_extra_tools(tmp_path):
    provider = NoStreamProvider(
        [
            ChatResponse(text="", tool_call=ToolCall(name="WriteFile", arguments={"path": "one.txt", "content": "1"})),
            ChatResponse(text="", tool_call=ToolCall(name="WriteFile", arguments={"path": "two.txt", "content": "2"})),
            ChatResponse(text="", tool_call=ToolCall(name="WriteFile", arguments={"path": "three.txt", "content": "3"})),
        ]
    )
    agent = SingleToolAgent(
        provider=provider,
        registry=default_registry(),
        context=ToolContext(root_dir=tmp_path),
        max_tool_steps=2,
    )
    session = ChatSession()

    result = agent.run_turn(session, "write three files")

    assert result.stop_reason == "max_steps"
    assert (tmp_path / "one.txt").exists()
    assert (tmp_path / "two.txt").exists()
    assert not (tmp_path / "three.txt").exists()


def test_agent_reports_missing_tool_arguments_and_lets_model_continue(tmp_path):
    provider = NoStreamProvider(
        [
            ChatResponse(text="", tool_call=ToolCall(name="Glob", arguments={})),
            ChatResponse(text="I need a pattern."),
        ]
    )
    agent = SingleToolAgent(provider=provider, registry=default_registry(), context=ToolContext(root_dir=tmp_path))
    session = ChatSession()

    result = agent.run_turn(session, "find files")

    assert result.tool_result["ok"] is False
    assert "Missing required arguments: pattern" in result.tool_result["error"]
    assert result.final_text == "I need a pattern."


def test_agent_counts_same_response_tool_calls_as_one_tool_step(tmp_path):
    (tmp_path / "a.py").write_text("a1", encoding="utf-8")
    (tmp_path / "b.py").write_text("b1", encoding="utf-8")
    provider = NoStreamProvider(
        [
            ChatResponse(
                text="",
                tool_calls=[
                    ToolCall(name="ReadFile", arguments={"path": "a.py"}),
                    ToolCall(name="ReadFile", arguments={"path": "b.py"}),
                ],
            ),
            ChatResponse(text="Read both files."),
        ]
    )
    context = ToolContext(root_dir=tmp_path)
    checker = PermissionChecker.from_workspace(context, mode="default", user_path=tmp_path / "missing-user.yaml")
    agent = SingleToolAgent(
        provider=provider,
        registry=default_registry(),
        context=context,
        permission_checker=checker,
        max_tool_steps=1,
    )
    session = ChatSession()

    result = agent.run_turn(session, "read two files")

    assert result.stop_reason == "final"
    assert [tool_call.name for tool_call in result.tool_calls] == ["ReadFile", "ReadFile"]
    assert [tool_call.arguments["path"] for tool_call in result.tool_calls] == ["a.py", "b.py"]
    assert [tool_result["ok"] for tool_result in result.tool_results] == [True, True]
    assert result.final_text == "Read both files."


def test_agent_allows_final_answer_after_reaching_tool_step_limit(tmp_path):
    (tmp_path / "a.py").write_text("a1", encoding="utf-8")
    provider = NoStreamProvider(
        [
            ChatResponse(text="", tool_call=ToolCall(name="ReadFile", arguments={"path": "a.py"})),
            ChatResponse(text="Final after one tool batch."),
        ]
    )
    agent = SingleToolAgent(
        provider=provider,
        registry=default_registry(),
        context=ToolContext(root_dir=tmp_path),
        max_tool_steps=1,
    )
    session = ChatSession()

    result = agent.run_turn(session, "read then summarize")

    assert result.stop_reason == "final"
    assert result.final_text == "Final after one tool batch."


def test_agent_default_max_tool_steps_is_twenty_four():
    assert DEFAULT_MAX_TOOL_STEPS == 24


def test_agent_can_call_mcp_tool_and_continue_loop(tmp_path):
    client = MCPClient(
        ScriptedTransport([make_success_response(1, {"content": [{"type": "text", "text": "issue #1"}]})]),
        "github",
    )
    registry = default_registry()
    registry.register(
        MCPToolWrapper(
            client=client,
            server_name="github",
            remote_tool=MCPTool(name="list_issues", description="List issues"),
            read_only=True,
        )
    )
    provider = NoStreamProvider(
        [
            ChatResponse(text="", tool_call=ToolCall(name="github__list_issues", arguments={})),
            ChatResponse(text="Found issue #1."),
        ]
    )
    context = ToolContext(root_dir=tmp_path)
    checker = PermissionChecker.from_workspace(context, mode="default", user_path=tmp_path / "missing-user.yaml")
    checker.add_read_tools({"github__list_issues"})
    agent = SingleToolAgent(provider=provider, registry=registry, context=context, permission_checker=checker)
    session = ChatSession()

    result = agent.run_turn(session, "list github issues")

    assert result.tool_result["ok"] is True
    assert result.tool_result["content"] == "issue #1"
    assert result.final_text == "Found issue #1."


def test_agent_reloads_tool_definitions_after_mcp_activation(tmp_path):
    class DynamicTool:
        def __init__(self):
            from mewcode.tools import ToolDefinition, ToolResult, ToolSchema

            self.definition = ToolDefinition(name="external__echo", description="Echo.", schema=ToolSchema())
            self.result_type = ToolResult

        def execute(self, arguments, context):
            return self.result_type(ok=True, content="activated")

    class ActivateTool:
        def __init__(self, registry):
            from mewcode.tools import ToolDefinition, ToolParameter, ToolResult, ToolSchema

            self.registry = registry
            self.result_type = ToolResult
            self.definition = ToolDefinition(
                name="ActivateMCPServer",
                description="Activate.",
                schema=ToolSchema(
                    properties={"server": ToolParameter(type="string", description="Server name.")},
                    required=["server"],
                ),
                requires_confirmation=True,
            )

        def execute(self, arguments, context):
            self.registry.register(DynamicTool())
            return self.result_type(ok=True, content="activated", metadata={"activated_read_tools": ["external__echo"]})

    registry = default_registry()
    registry.register(ActivateTool(registry))
    provider = NoStreamProvider(
        [
            ChatResponse(text="", tool_call=ToolCall(name="ActivateMCPServer", arguments={"server": "external"})),
            ChatResponse(text="", tool_call=ToolCall(name="external__echo", arguments={})),
            ChatResponse(text="Done."),
        ]
    )
    context = ToolContext(root_dir=tmp_path)
    checker = PermissionChecker.from_workspace(context, mode="bypassPermissions", user_path=tmp_path / "missing-user.yaml")
    checker.add_read_tools({"external__echo"})
    agent = SingleToolAgent(provider=provider, registry=registry, context=context, permission_checker=checker)
    session = ChatSession()

    result = agent.run_turn(session, "activate external")

    first_request_tools = {tool["name"] for tool in provider.calls[0]["tools"]}
    second_request_tools = {tool["name"] for tool in provider.calls[1]["tools"]}
    assert "external__echo" not in first_request_tools
    assert "external__echo" in second_request_tools
    assert result.final_text == "Done."


def test_legacy_confirm_and_deny_methods_remain_callable(tmp_path):
    provider = NoStreamProvider([ChatResponse(text="Created the file."), ChatResponse(text="Denied.")])
    agent = SingleToolAgent(provider=provider, registry=default_registry(), context=ToolContext(root_dir=tmp_path))
    pending = PendingToolRequest(tool_call=ToolCall(name="WriteFile", arguments={"path": "note.txt", "content": "hi"}))

    confirmed = agent.confirm_pending(ChatSession(), pending)
    denied = agent.deny_pending(ChatSession(), pending)

    assert confirmed.tool_result["ok"] is True
    assert denied.tool_result["metadata"]["denied"] is True


def test_agent_spills_large_tool_result_before_adding_to_history(tmp_path):
    large_file = tmp_path / "large.txt"
    large_file.write_text("x" * 51000, encoding="utf-8")
    provider = NoStreamProvider(
        [
            ChatResponse(text="", tool_call=ToolCall(name="ReadFile", arguments={"path": "large.txt"})),
            ChatResponse(text="Summarized."),
        ]
    )
    context_manager = ContextManager(root_dir=tmp_path, provider=provider)
    agent = SingleToolAgent(
        provider=provider,
        registry=default_registry(),
        context=ToolContext(root_dir=tmp_path, max_output_chars=60000),
        context_manager=context_manager,
    )
    session = ChatSession()

    result = agent.run_turn(session, "read large")

    assert result.tool_result["metadata"]["stored_on_disk"] is True
    assert session.messages[2]["tool_result"]["metadata"]["stored_on_disk"] is True
    assert (tmp_path / result.tool_result["metadata"]["stored_path"]).exists()
    assert result.final_text == "Summarized."


def test_agent_stream_emits_tool_result_spilled_event(tmp_path):
    large_file = tmp_path / "large.txt"
    large_file.write_text("x" * 51000, encoding="utf-8")
    provider = NoStreamProvider(
        [
            ChatResponse(text="", tool_call=ToolCall(name="ReadFile", arguments={"path": "large.txt"})),
            ChatResponse(text="Summarized."),
        ]
    )
    context_manager = ContextManager(root_dir=tmp_path, provider=provider)
    agent = SingleToolAgent(
        provider=provider,
        registry=default_registry(),
        context=ToolContext(root_dir=tmp_path, max_output_chars=60000),
        context_manager=context_manager,
    )

    events = list(agent.stream_turn(ChatSession(), "read large"))
    spill_events = [event for event in events if isinstance(event, ToolResultSpilled)]

    assert len(spill_events) == 1
    assert spill_events[0].count == 1
    assert spill_events[0].freed_chars > 0
    assert spill_events[0].stored_path.endswith("ReadFile_0")
    assert next(index for index, event in enumerate(events) if isinstance(event, ToolFinished)) < next(
        index for index, event in enumerate(events) if isinstance(event, ToolResultSpilled)
    )


def test_agent_emergency_compacts_on_prompt_too_long_and_retries_once(tmp_path):
    class PromptTooLongProvider(NoStreamProvider):
        def __init__(self):
            super().__init__([ChatResponse(text="<final_summary>Recovered context.</final_summary>"), ChatResponse(text="ok")])
            self.failed_once = False

        def complete_chat(self, messages, tools=None):
            self.calls.append({"messages": messages, "tools": tools})
            if not messages.metadata.get("context_compaction") and not self.failed_once:
                self.failed_once = True
                raise RuntimeError("prompt_too_long")
            return self.responses.pop(0)

    provider = PromptTooLongProvider()
    manager = ContextManager(root_dir=tmp_path, provider=provider, config=ContextConfig(min_recent_messages=2))
    agent = SingleToolAgent(
        provider=provider,
        registry=default_registry(),
        context=ToolContext(root_dir=tmp_path),
        context_manager=manager,
    )
    session = ChatSession()
    for index in range(8):
        session.add_user_message(f"old {index}")

    events = list(agent.stream_turn(session, "continue"))

    assert any(isinstance(event, ContextCompressionFinished) for event in events)
    assert any(isinstance(event, ContextEmergencyRetry) for event in events)
    assert session.messages[-1]["content"] == "ok"
    assert provider.failed_once is True


def test_agent_emits_auto_compact_started_before_summary_request(tmp_path):
    provider = NoStreamProvider([ChatResponse(text="<final_summary>summary</final_summary>"), ChatResponse(text="done")])
    manager = ContextManager(
        root_dir=tmp_path,
        provider=provider,
        config=ContextConfig(context_window_tokens=50, auto_margin_tokens=10, min_recent_messages=2),
    )
    agent = SingleToolAgent(
        provider=provider,
        registry=default_registry(),
        context=ToolContext(root_dir=tmp_path),
        context_manager=manager,
    )
    session = ChatSession()
    for index in range(8):
        session.add_user_message("x" * 80)

    stream = agent.stream_turn(session, "continue")
    first_event = next(stream)

    assert isinstance(first_event, ContextCompressionStarted)
    assert provider.calls == []


def test_agent_stream_compact_passes_focus_to_context_manager(tmp_path):
    provider = NoStreamProvider([ChatResponse(text="<summary>focused</summary>")])
    manager = ContextManager(root_dir=tmp_path, provider=provider, config=ContextConfig(min_recent_messages=2))
    agent = SingleToolAgent(
        provider=provider,
        registry=default_registry(),
        context=ToolContext(root_dir=tmp_path),
        context_manager=manager,
    )
    session = ChatSession()
    for index in range(8):
        session.add_user_message(f"user {index}")

    events = list(agent.stream_compact(session, focus="keep context.py details"))

    assert any(isinstance(event, ContextCompressionFinished) for event in events)
    assert "keep context.py details" in provider.calls[0]["messages"].messages[0]["content"]


def test_agent_stream_context_stats_emits_report(tmp_path):
    provider = NoStreamProvider([ChatResponse(text="unused")])
    manager = ContextManager(root_dir=tmp_path, provider=provider)
    agent = SingleToolAgent(
        provider=provider,
        registry=default_registry(),
        context=ToolContext(root_dir=tmp_path),
        context_manager=manager,
    )
    session = ChatSession()
    session.add_user_message("hello")

    events = list(agent.stream_context_stats(session))

    assert any(isinstance(event, ContextStatsReported) for event in events)
    assert events[-1].reason == "context"
