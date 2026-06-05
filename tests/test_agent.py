from mewcode.agent import DEFAULT_MAX_TOOL_STEPS, PendingToolRequest, SingleToolAgent, UserQuestionRequested
from mewcode.providers.base import ChatResponse, ToolCall
from mewcode.session import ChatSession
from mewcode.tools.context import ToolContext
from mewcode.tools.registry import default_registry


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
    assert session.messages[0]["content"].startswith("You are in MewCode Plan Mode.")


def test_agent_plan_mode_can_write_plan_file_but_still_blocks_source_writes(tmp_path):
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

    assert (tmp_path / "plans" / "shop.md").read_text(encoding="utf-8") == "# Plan\n\nBuild MVP."
    assert not (tmp_path / "app.py").exists()
    assert [tool_result["ok"] for tool_result in result.tool_results] == [True, False]
    assert result.tool_results[0]["metadata"]["plan_file"] is True
    assert result.tool_results[1]["metadata"]["blocked_by_plan_mode"] is True
    assert result.final_text == "Plan file is ready. Please accept or adjust it."


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
            ChatResponse(
                text="",
                tool_calls=[
                    ToolCall(name="WriteFile", arguments={"path": "one.txt", "content": "1"}),
                    ToolCall(name="WriteFile", arguments={"path": "two.txt", "content": "2"}),
                    ToolCall(name="WriteFile", arguments={"path": "three.txt", "content": "3"}),
                ],
            ),
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


def test_agent_default_max_tool_steps_is_eight():
    assert DEFAULT_MAX_TOOL_STEPS == 8


def test_legacy_confirm_and_deny_methods_remain_callable(tmp_path):
    provider = NoStreamProvider([ChatResponse(text="Created the file."), ChatResponse(text="Denied.")])
    agent = SingleToolAgent(provider=provider, registry=default_registry(), context=ToolContext(root_dir=tmp_path))
    pending = PendingToolRequest(tool_call=ToolCall(name="WriteFile", arguments={"path": "note.txt", "content": "hi"}))

    confirmed = agent.confirm_pending(ChatSession(), pending)
    denied = agent.deny_pending(ChatSession(), pending)

    assert confirmed.tool_result["ok"] is True
    assert denied.tool_result["metadata"]["denied"] is True
