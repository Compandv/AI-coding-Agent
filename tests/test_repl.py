import asyncio
from io import StringIO
from pathlib import Path

from textual.widgets import Input

from mewcode.agent import (
    AgentTurnResult,
    ClarificationQuestion,
    ConfirmationRequired,
    PendingToolRequest,
    QuestionOption,
    TextDelta,
    ToolFinished,
    ToolStarted,
    TurnComplete,
    UserQuestionRequested,
)
from mewcode.config import MewCodeConfig
from mewcode.providers.base import ToolCall
from mewcode.repl import (
    ASCII_SPINNER_FRAMES,
    BRAILLE_SPINNER_FRAMES,
    DisplayMessage,
    FOOTER_HINT,
    MEWCODE_LOGO,
    MewCodeApp,
    MewCodeRepl,
    assistant_message_text,
    clarification_questions_text,
    confirmation_status_text,
    interrupted_status_text,
    last_assistant_text,
    model_status_line,
    question_message_text,
    should_use_line_mode_for_terminal,
    spinner_frames,
    status_message_text,
    tool_action_label,
    tool_result_text,
    tool_running_text,
    transcript_text,
    user_message_text,
)


class FakeProvider:
    pass


class FakeAgent:
    def __init__(self, result=None, confirm_result=None, deny_result=None, stream_events=None):
        self.result = result
        self.confirm_result = confirm_result
        self.deny_result = deny_result
        self.stream_events = stream_events
        self.calls = []
        self.confirm_calls = []
        self.deny_calls = []

    def _events_for(self, result):
        if self.stream_events is not None:
            return list(self.stream_events)
        events = []
        if result is not None and result.final_text:
            events.append(TextDelta(text=result.final_text))
        if result is not None and result.needs_confirmation and result.pending_request is not None:
            events.append(ConfirmationRequired(pending_request=result.pending_request))
        else:
            events.append(TurnComplete())
        return events

    def run_turn(self, session, text, mode="normal"):
        self.calls.append({"session": session, "text": text, "mode": mode})
        return self.result

    def confirm_pending(self, session, pending):
        self.confirm_calls.append({"session": session, "pending": pending})
        return self.confirm_result

    def deny_pending(self, session, pending):
        self.deny_calls.append({"session": session, "pending": pending})
        return self.deny_result

    def stream_turn(self, session, text, mode="normal"):
        self.calls.append({"session": session, "text": text, "mode": mode})
        yield from self._events_for(self.result)

    def stream_confirm(self, session, pending):
        self.confirm_calls.append({"session": session, "pending": pending})
        yield from self._events_for(self.confirm_result)

    def stream_deny(self, session, pending):
        self.deny_calls.append({"session": session, "pending": pending})
        yield from self._events_for(self.deny_result)


class SequencedStreamAgent:
    def __init__(self, event_batches):
        self.event_batches = [list(batch) for batch in event_batches]
        self.calls = []

    def stream_turn(self, session, text, mode="normal"):
        self.calls.append({"session": session, "text": text, "mode": mode})
        if not self.event_batches:
            yield TurnComplete(reason="final")
            return
        yield from self.event_batches.pop(0)


def config() -> MewCodeConfig:
    return MewCodeConfig(
        protocol="openai",
        model="gpt-4.1",
        base_url="https://api.openai.com/v1",
        api_key="secret",
    )


def ecommerce_questions() -> list[ClarificationQuestion]:
    return [
        ClarificationQuestion(
            id="scope",
            title="Project scope",
            question="Where should the ecommerce system live?",
            options=[
                QuestionOption(
                    label="Inside current repo",
                    description="Add the plan for the existing repository.",
                    recommended=True,
                ),
                QuestionOption(label="Standalone project", description="Create a separate application."),
            ],
        ),
        ClarificationQuestion(
            id="stack",
            title="Tech stack",
            question="Which stack should the plan target?",
            options=[
                QuestionOption(label="Python + FastAPI", description="API-first backend."),
                QuestionOption(label="Go + SQLite", description="Small self-contained backend."),
            ],
        ),
    ]


def test_logo_is_block_style_and_header_uses_agent_branding():
    repl = MewCodeRepl(
        provider=FakeProvider(),
        config=config(),
        cwd=Path("E:/Agent_Learn/AI-Coding-Agent"),
        version="0.1.0",
    )

    header = repl.header_text()

    assert "███" in MEWCODE_LOGO
    assert "MewCode Agent v0.1.0" in header
    assert "gpt-4.1 with high effort" in header
    assert "cwd:E:" in header


def test_model_status_line_mentions_model_effort_and_billing():
    assert model_status_line(config()) == "gpt-4.1 with high effort · API Usage Billing"


def test_message_markers_are_colored_and_distinct():
    assert user_message_text("hello") == "[bold blue]>[/bold blue] hello"
    assert assistant_message_text("hello") == "[bold magenta]●[/bold magenta] hello"


def test_message_text_escapes_rich_markup_from_model_content():
    assert user_message_text("look at [README]") == "[bold blue]>[/bold blue] look at \\[README]"
    assert assistant_message_text('```json\n["entry"]\n```') == (
        '[bold magenta]●[/bold magenta] ```json\n\\["entry"]\n```'
    )


def test_status_text_uses_phase_colors_spinner_icon_and_elapsed_time():
    assert status_message_text("⠋", "Thinking", 8) == "[bold yellow]⠋ Thinking... (8s)[/bold yellow]"
    assert status_message_text("⠙", "Coding", 9) == "[bold cyan]⠙ Coding... (9s)[/bold cyan]"
    assert interrupted_status_text(10) == "[bold red]* Done (interrupted · 10s)[/bold red]"


def test_tool_status_text_uses_action_target_and_elapsed_time():
    read_call = ToolCall(name="ReadFile", arguments={"path": "src/mewcode/tools/search_tools.py"})
    glob_call = ToolCall(name="Glob", arguments={"pattern": "**/main.py"})
    plan_call = ToolCall(name="WritePlanFile", arguments={"path": "plans/shop.md", "content": "# Plan\n\nStep 1"})

    assert tool_action_label(read_call) == "Read src/mewcode/tools/search_tools.py"
    assert tool_action_label(glob_call) == "Glob: **/main.py"
    assert tool_action_label(plan_call) == "Write plan plans/shop.md (3 lines)"
    assert tool_running_text(read_call, "|", 1.2) == (
        "[bold cyan]| Read src/mewcode/tools/search_tools.py (1.2s)[/bold cyan]"
    )
    assert tool_result_text(glob_call, True, 0.3) == "[bold green]✓ Glob: **/main.py (0.3s)[/bold green]"


def test_spinner_frames_fall_back_for_plain_windows_console(monkeypatch):
    monkeypatch.delenv("TERM_PROGRAM", raising=False)
    monkeypatch.delenv("WT_SESSION", raising=False)
    monkeypatch.setenv("TERM", "")

    class FakeStdout:
        encoding = "cp936"

    monkeypatch.setattr("mewcode.repl.sys.stdout", FakeStdout())

    assert spinner_frames() == ASCII_SPINNER_FRAMES


def test_spinner_frames_use_braille_in_vscode(monkeypatch):
    monkeypatch.setenv("TERM_PROGRAM", "vscode")

    assert spinner_frames() == BRAILLE_SPINNER_FRAMES


def test_windows_vscode_terminal_defaults_to_textual_mode(monkeypatch):
    monkeypatch.delenv("MEWCODE_UI", raising=False)
    monkeypatch.setenv("TERM_PROGRAM", "vscode")
    monkeypatch.setattr("mewcode.repl.sys.platform", "win32")

    assert should_use_line_mode_for_terminal() is False


def test_ui_env_can_force_line_mode(monkeypatch):
    monkeypatch.setenv("MEWCODE_UI", "line")
    monkeypatch.setenv("TERM_PROGRAM", "vscode")
    monkeypatch.setattr("mewcode.repl.sys.platform", "win32")

    assert should_use_line_mode_for_terminal() is True


def test_ui_env_can_force_textual_mode(monkeypatch):
    monkeypatch.setenv("MEWCODE_UI", "tui")

    assert should_use_line_mode_for_terminal() is False


def test_transcript_helpers_keep_unicode_text():
    messages = [
        DisplayMessage("status", "Ready."),
        DisplayMessage("user", "帮我看一下项目入口文件"),
        DisplayMessage("assistant", "入口在 src/mewcode/cli.py"),
        DisplayMessage("assistant", "最终回答"),
    ]

    assert last_assistant_text(messages) == "最终回答"
    assert transcript_text(messages) == (
        "User: 帮我看一下项目入口文件\n\n"
        "Assistant: 入口在 src/mewcode/cli.py\n\n"
        "Assistant: 最终回答"
    )


def test_textual_app_header_removes_learning_tag_and_exposes_mode_hint():
    app = MewCodeApp(provider=FakeProvider(), config=config(), version="0.1.0")

    assert app.title_line == "MewCode Agent v0.1.0"
    assert app.model_line == "gpt-4.1 with high effort · API Usage Billing"
    assert FOOTER_HINT == (
        "esc interrupt · ctrl+c copy · ctrl+y last answer · ctrl+shift+y transcript · ctrl+q quit"
    )


def test_textual_input_keeps_focus_after_mount_and_submit():
    async def run_app() -> None:
        agent = FakeAgent(result=AgentTurnResult(final_text="hello"))
        app = MewCodeApp(provider=FakeProvider(), config=config(), version="0.1.0", agent=agent)

        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt-input", Input)
            await pilot.pause()
            assert prompt.has_focus

            prompt.value = "hello"
            await pilot.press("enter")
            await pilot.pause()

            assert prompt.has_focus
            assert agent.calls[0]["text"] == "hello"

    asyncio.run(run_app())


def test_textual_input_accepts_slash_from_keyboard():
    async def run_app() -> None:
        agent = FakeAgent(result=AgentTurnResult(final_text="ok"))
        app = MewCodeApp(provider=FakeProvider(), config=config(), version="0.1.0", agent=agent)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("slash", "i", "n", "i", "t", "enter")
            await pilot.pause()

            assert agent.calls[0]["text"] == "/init"

    asyncio.run(run_app())


def test_textual_streaming_answer_with_brackets_does_not_raise_markup_error():
    async def run_app() -> None:
        agent = FakeAgent(result=AgentTurnResult(final_text='```json\n["entry"]\n```'))
        app = MewCodeApp(provider=FakeProvider(), config=config(), version="0.1.0", agent=agent)

        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt-input", Input)
            await pilot.pause()
            prompt.value = "show json"
            await pilot.press("enter")
            await pilot.pause()

            assert agent.calls[0]["text"] == "show json"
            assert any(message.content == '```json\n["entry"]\n```' for message in app.messages)

    asyncio.run(run_app())


def test_textual_tool_status_updates_to_finished_file_target():
    async def run_app() -> None:
        tool_call = ToolCall(name="ReadFile", arguments={"path": "src/mewcode/tools/search_tools.py"})
        agent = FakeAgent(
            stream_events=[
                ToolStarted(tool_call=tool_call),
                ToolFinished(tool_call=tool_call, result={"ok": True, "content": "", "metadata": {}}),
                TextDelta(text="done"),
                TurnComplete(),
            ]
        )
        app = MewCodeApp(provider=FakeProvider(), config=config(), version="0.1.0", agent=agent)

        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt-input", Input)
            await pilot.pause()
            prompt.value = "read file"
            await pilot.press("enter")
            await pilot.pause()

            tool_messages = [
                message.content
                for message in app.messages
                if "src/mewcode/tools/search_tools.py" in message.content
            ]

            assert len(tool_messages) == 1
            assert tool_messages[0].startswith("[bold green]✓ Read src/mewcode/tools/search_tools.py (")
            assert tool_messages[0].endswith("s)[/bold green]")

    asyncio.run(run_app())


def test_textual_clarification_panel_navigates_answers_and_submits_plan_mode():
    async def run_app() -> None:
        tool_call = ToolCall(name="AskUserQuestion", arguments={"questions": []})
        questions = ecommerce_questions()
        question_event = UserQuestionRequested(tool_call=tool_call, questions=questions)
        agent = SequencedStreamAgent(
            [
                [
                    ToolStarted(tool_call=tool_call),
                    ToolFinished(tool_call=tool_call, result={"ok": True, "content": "", "metadata": {"await_user": True}}),
                    question_event,
                    TurnComplete(reason="await_user"),
                ],
                [TextDelta(text="Plan ready."), TurnComplete(reason="final")],
            ]
        )
        app = MewCodeApp(provider=FakeProvider(), config=config(), version="0.1.0", agent=agent)

        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt-input", Input)
            await pilot.pause()
            prompt.value = "/plan build ecommerce"
            await pilot.press("enter")
            await pilot.pause()

            assert agent.calls[0]["mode"] == "plan"
            assert app._clarification_state is not None
            assert app._clarification_state.question_index == 0
            assert app._phase == "Cultivating"

            await pilot.press("right")
            await pilot.pause()
            assert app._clarification_state is not None
            assert app._clarification_state.question_index == 0

            await pilot.press("down", "enter")
            await pilot.pause()
            assert app._clarification_state is not None
            assert app._clarification_state.question_index == 1

            await pilot.press("left", "up", "enter")
            await pilot.pause()
            assert app._clarification_state is not None
            assert app._clarification_state.question_index == 1

            await pilot.press("down", "enter")
            await pilot.pause()
            assert app._clarification_state is not None
            assert app._clarification_state.question_index == len(questions)

            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()

            assert app._clarification_state is None
            assert len(agent.calls) == 2
            assert agent.calls[1]["mode"] == "plan"
            assert "Clarification answers:" in agent.calls[1]["text"]
            assert "- Project scope: Inside current repo" in agent.calls[1]["text"]
            assert "- Tech stack: Go + SQLite" in agent.calls[1]["text"]
            assert any(message.content == "Plan ready." for message in app.messages)

    asyncio.run(run_app())


def test_textual_clarification_other_option_accepts_custom_input():
    async def run_app() -> None:
        tool_call = ToolCall(name="AskUserQuestion", arguments={"questions": []})
        questions = [
            ClarificationQuestion(
                id="stack",
                title="Tech stack",
                question="Which stack should the plan target?",
                options=[
                    QuestionOption(label="Python + FastAPI", description="API-first backend."),
                    QuestionOption(
                        label="Other",
                        description="Type a stack manually.",
                        allow_custom_input=True,
                    ),
                ],
            )
        ]
        question_event = UserQuestionRequested(tool_call=tool_call, questions=questions)
        agent = SequencedStreamAgent(
            [
                [
                    ToolStarted(tool_call=tool_call),
                    ToolFinished(tool_call=tool_call, result={"ok": True, "content": "", "metadata": {"await_user": True}}),
                    question_event,
                    TurnComplete(reason="await_user"),
                ],
                [TextDelta(text="Plan ready."), TurnComplete(reason="final")],
            ]
        )
        app = MewCodeApp(provider=FakeProvider(), config=config(), version="0.1.0", agent=agent)

        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt-input", Input)
            await pilot.pause()
            prompt.value = "/plan build ecommerce"
            await pilot.press("enter")
            await pilot.pause()

            await pilot.press("down")
            await pilot.pause()
            assert app._clarification_state is not None
            assert app._clarification_state.question_index == 0

            await pilot.press("enter")
            await pilot.pause()
            assert app._clarification_state is not None
            assert app._clarification_state.question_index == 0
            assert not app._clarification_state.all_answered()

            prompt.value = "Vue + NestJS"
            await pilot.press("enter")
            await pilot.pause()
            assert app._clarification_state is not None
            assert app._clarification_state.question_index == len(questions)

            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()

            assert app._clarification_state is None
            assert len(agent.calls) == 2
            assert "Clarification answers:" in agent.calls[1]["text"]
            assert "- Tech stack: Vue + NestJS" in agent.calls[1]["text"]
            assert "- Tech stack: Other" not in agent.calls[1]["text"]
            assert any(message.content == "Plan ready." for message in app.messages)

    asyncio.run(run_app())


def test_textual_can_copy_last_answer_without_terminal_selection(monkeypatch):
    copied = []

    async def run_app() -> None:
        agent = FakeAgent(result=AgentTurnResult(final_text="中文回答"))
        app = MewCodeApp(provider=FakeProvider(), config=config(), version="0.1.0", agent=agent)
        monkeypatch.setattr("mewcode.repl.set_system_clipboard_text", lambda text: copied.append(text) or True)

        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt-input", Input)
            await pilot.pause()
            prompt.value = "问题"
            await pilot.press("enter")
            await pilot.pause()

            app.action_copy_last_answer()
            await pilot.pause()

            assert app.clipboard == "中文回答"
            assert copied == ["中文回答"]

    asyncio.run(run_app())


def test_textual_copy_to_clipboard_also_writes_system_clipboard(monkeypatch):
    copied = []

    async def run_app() -> None:
        app = MewCodeApp(provider=FakeProvider(), config=config(), version="0.1.0")
        monkeypatch.setattr("mewcode.repl.set_system_clipboard_text", lambda text: copied.append(text) or True)

        async with app.run_test() as pilot:
            await pilot.pause()

            app.copy_to_clipboard("选中的中文")

            assert app.clipboard == "选中的中文"
            assert copied == ["选中的中文"]

    asyncio.run(run_app())


def test_textual_copy_last_answer_binding_works_with_input_focused(monkeypatch):
    copied = []

    async def run_app() -> None:
        agent = FakeAgent(result=AgentTurnResult(final_text="中文回答"))
        app = MewCodeApp(provider=FakeProvider(), config=config(), version="0.1.0", agent=agent)
        monkeypatch.setattr("mewcode.repl.set_system_clipboard_text", lambda text: copied.append(text) or True)

        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt-input", Input)
            await pilot.pause()
            prompt.value = "问题"
            await pilot.press("enter")
            await pilot.pause()

            assert prompt.has_focus
            await pilot.press("ctrl+y")
            await pilot.pause()

            assert app.clipboard == "中文回答"
            assert copied == ["中文回答"]

    asyncio.run(run_app())


def test_textual_ctrl_c_copies_last_answer_when_no_selection(monkeypatch):
    copied = []

    async def run_app() -> None:
        agent = FakeAgent(result=AgentTurnResult(final_text="中文回答"))
        app = MewCodeApp(provider=FakeProvider(), config=config(), version="0.1.0", agent=agent)
        monkeypatch.setattr("mewcode.repl.set_system_clipboard_text", lambda text: copied.append(text) or True)

        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt-input", Input)
            await pilot.pause()
            prompt.value = "问题"
            await pilot.press("enter")
            await pilot.pause()

            assert prompt.has_focus
            await pilot.press("ctrl+c")
            await pilot.pause()

            assert app.clipboard == "中文回答"
            assert copied == ["中文回答"]

    asyncio.run(run_app())


def test_textual_ctrl_c_copies_selection_when_textual_receives_key(monkeypatch):
    copied = []

    async def run_app() -> None:
        app = MewCodeApp(provider=FakeProvider(), config=config(), version="0.1.0")
        monkeypatch.setattr("mewcode.repl.set_system_clipboard_text", lambda text: copied.append(text) or True)

        async with app.run_test() as pilot:
            await pilot.pause()
            monkeypatch.setattr(app.screen, "get_selected_text", lambda: "选中的中文")

            await pilot.press("ctrl+c")
            await pilot.pause()

            assert app.clipboard == "选中的中文"
            assert copied == ["选中的中文"]

    asyncio.run(run_app())


def test_textual_can_copy_transcript_without_terminal_selection(monkeypatch):
    copied = []

    async def run_app() -> None:
        agent = FakeAgent(result=AgentTurnResult(final_text="中文回答"))
        app = MewCodeApp(provider=FakeProvider(), config=config(), version="0.1.0", agent=agent)
        monkeypatch.setattr("mewcode.repl.set_system_clipboard_text", lambda text: copied.append(text) or True)

        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt-input", Input)
            await pilot.pause()
            prompt.value = "问题"
            await pilot.press("enter")
            await pilot.pause()

            app.action_copy_transcript()
            await pilot.pause()

            assert app.clipboard == "User: 问题\n\nAssistant: 中文回答"
            assert copied == ["User: 问题\n\nAssistant: 中文回答"]

    asyncio.run(run_app())


def test_line_mode_consumes_agent_events_and_reports_tool_status():
    tool_call = ToolCall(name="ReadFile", arguments={"path": "src/mewcode/repl.py"})
    agent = FakeAgent(
        stream_events=[
            ToolStarted(tool_call=tool_call),
            ToolFinished(tool_call=tool_call, result={"ok": True, "content": "", "metadata": {}}),
            TextDelta(text="Read complete."),
            TurnComplete(reason="final"),
        ]
    )
    inputs = iter(["hello", "/quit"])
    output = StringIO()
    repl = MewCodeRepl(provider=FakeProvider(), config=config(), input_func=lambda prompt: next(inputs), output=output, agent=agent)

    assert repl.run() == 0

    rendered = output.getvalue()
    assert "> hello" in rendered
    assert "* Running Read src/mewcode/repl.py" in rendered
    assert "* Read src/mewcode/repl.py ok" in rendered
    assert "Read complete." in rendered
    assert "* Done (final)" in rendered


def test_line_mode_plan_and_do_are_persistent_mode_switches():
    agent = FakeAgent(result=AgentTurnResult(final_text="ok"))
    inputs = iter(["/plan inspect project", "/do", "execute changes", "/quit"])
    output = StringIO()
    repl = MewCodeRepl(provider=FakeProvider(), config=config(), input_func=lambda prompt: next(inputs), output=output, agent=agent)

    assert repl.run() == 0

    assert agent.calls == [
        {"session": repl.session, "text": "inspect project", "mode": "plan"},
        {"session": repl.session, "text": "execute changes", "mode": "normal"},
    ]
    rendered = output.getvalue()
    assert "* Plan Mode: read-only tools enabled. Use /do to execute changes." in rendered
    assert "* Do Mode: tools can write files and run commands. Use /plan for read-only planning." in rendered


def test_line_mode_reports_blocked_plan_mode_tool_result():
    tool_call = ToolCall(name="WriteFile", arguments={"path": "note.txt", "content": "hi"})
    agent = FakeAgent(
        stream_events=[
            ToolStarted(tool_call=tool_call),
            ToolFinished(
                tool_call=tool_call,
                result={
                    "ok": False,
                    "content": "",
                    "error": "Plan Mode blocked unsafe tool: WriteFile",
                    "metadata": {"blocked_by_plan_mode": True},
                },
            ),
            TextDelta(text="Plan: create note.txt after approval."),
            TurnComplete(reason="final"),
        ]
    )
    inputs = iter(["/plan create note", "/quit"])
    output = StringIO()
    repl = MewCodeRepl(provider=FakeProvider(), config=config(), input_func=lambda prompt: next(inputs), output=output, agent=agent)

    assert repl.run() == 0
    assert agent.calls[0]["mode"] == "plan"
    rendered = output.getvalue()
    assert "* Write note.txt failed: Plan Mode blocked unsafe tool: WriteFile" in rendered
    assert "Plan: create note.txt after approval." in rendered


def test_line_mode_displays_user_question_and_waits_for_clarification():
    tool_call = ToolCall(name="AskUserQuestion", arguments={"question": "Project location?", "options": ["New", "Existing"]})
    agent = FakeAgent(
        stream_events=[
            ToolStarted(tool_call=tool_call),
            ToolFinished(
                tool_call=tool_call,
                result={
                    "ok": True,
                    "content": "Project location?\n- New\n- Existing",
                    "metadata": {"await_user": True, "question": "Project location?", "options": ["New", "Existing"]},
                },
            ),
            UserQuestionRequested(tool_call=tool_call, question="Project location?", options=["New", "Existing"]),
            TurnComplete(reason="await_user"),
        ]
    )
    inputs = iter(["/plan build ecommerce", "/quit"])
    output = StringIO()
    repl = MewCodeRepl(provider=FakeProvider(), config=config(), input_func=lambda prompt: next(inputs), output=output, agent=agent)

    assert repl.run() == 0

    rendered = output.getvalue()
    assert "* Running AskUserQuestion" in rendered
    assert "* AskUserQuestion ok" in rendered
    assert "Project location?\n- New\n- Existing" in rendered
    assert "* Waiting for your clarification. Reply with the answer to continue planning." in rendered
    assert "* Done (await_user)" not in rendered


def test_line_mode_remembers_plan_file_and_accepts_it():
    tool_call = ToolCall(name="WritePlanFile", arguments={"path": "plans/shop.md", "content": "# Plan"})
    agent = FakeAgent(
        stream_events=[
            ToolStarted(tool_call=tool_call),
            ToolFinished(
                tool_call=tool_call,
                result={
                    "ok": True,
                    "content": "Wrote plan file: plans/shop.md",
                    "metadata": {"plan_file": True, "relative_path": "plans/shop.md"},
                },
            ),
            TextDelta(text="Plan ready."),
            TurnComplete(reason="final"),
        ]
    )
    inputs = iter(["/plan build ecommerce", "/accept", "/quit"])
    output = StringIO()
    repl = MewCodeRepl(provider=FakeProvider(), config=config(), input_func=lambda prompt: next(inputs), output=output, agent=agent)

    assert repl.run() == 0

    rendered = output.getvalue()
    assert "* Write plan plans/shop.md (1 lines) ok" in rendered
    assert "* Accepted plan: plans/shop.md. Use /do to start implementation or /plan to adjust." in rendered


def test_question_message_text_formats_options():
    assert question_message_text("Project location?", ["New", "Existing"]) == "Project location?\n- New\n- Existing"


def test_confirmation_status_text_mentions_tool_name():
    assert confirmation_status_text("WriteFile") == "[bold yellow]* Confirmation required for WriteFile (reply yes/no)[/bold yellow]"


def test_tool_result_text_shows_failure_detail():
    tool_call = ToolCall(name="Glob", arguments={"pattern": "[bad]"})

    assert tool_result_text(tool_call, False, 2.4, "Missing required arguments: pattern") == (
        "[bold red]x Glob: \\[bad] failed (2.4s): Missing required arguments: pattern[/bold red]"
    )


def test_line_mode_skips_empty_input():
    agent = FakeAgent(result=AgentTurnResult(final_text="unused"))
    inputs = iter(["", "   ", "/exit"])
    output = StringIO()
    repl = MewCodeRepl(provider=FakeProvider(), config=config(), input_func=lambda prompt: next(inputs), output=output, agent=agent)

    assert repl.run() == 0

    assert agent.calls == []
