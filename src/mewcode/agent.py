from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

from mewcode.providers.base import ChatProvider, ChatResponse, StreamChunk, ToolCall
from mewcode.session import ChatSession
from mewcode.tools import ToolContext, ToolError, ToolRegistry


AgentMode = Literal["normal", "plan"]
DEFAULT_MAX_TOOL_STEPS = 8
PLAN_MODE_PREFIX = (
    "You are in MewCode Plan Mode. First clarify broad or ambiguous requests with AskUserQuestion. "
    "If you already know several important clarifications, ask them in one AskUserQuestion call with a questions list. "
    "Inspect the project with read-only tools only. Do not write source files, edit source files, or run shell commands. "
    "You may write Markdown implementation plans with WritePlanFile under plans/ or docs/plans/. "
    "When the plan is ready, summarize the plan file and ask the user to accept it or request adjustments.\n\n"
)


@dataclass
class PendingToolRequest:
    tool_call: ToolCall


@dataclass
class AgentTurnResult:
    final_text: str
    tool_call: ToolCall | None = None
    tool_result: dict[str, Any] | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str = "final"
    needs_confirmation: bool = False
    pending_request: PendingToolRequest | None = None


@dataclass
class TextDelta:
    """A chunk of assistant text as it streams in."""

    text: str


@dataclass
class AgentStatus:
    phase: str


@dataclass
class ToolStarted:
    """A tool is about to execute."""

    tool_call: ToolCall


@dataclass
class ToolFinished:
    """A tool finished; result is the message-content payload."""

    tool_call: ToolCall
    result: dict[str, Any]


@dataclass
class ConfirmationRequired:
    """Compatibility event retained from chapter 3; not emitted by chapter 4 normal flow."""

    pending_request: PendingToolRequest


@dataclass
class AgentError:
    message: str


@dataclass
class QuestionOption:
    label: str
    description: str = ""
    recommended: bool = False
    allow_custom_input: bool = False


@dataclass
class ClarificationQuestion:
    id: str
    title: str
    question: str
    options: list[QuestionOption] = field(default_factory=list)


@dataclass
class UserQuestionRequested:
    tool_call: ToolCall
    question: str = ""
    options: list[str] = field(default_factory=list)
    reason: str = ""
    questions: list[ClarificationQuestion] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.questions or not self.question:
            return
        self.questions = [
            ClarificationQuestion(
                id="question_1",
                title="Question 1",
                question=self.question,
                options=[QuestionOption(label=option) for option in self.options],
            )
        ]


@dataclass
class TurnCancelled:
    reason: str = "cancelled"


@dataclass
class TurnComplete:
    """The turn finished and no further input is awaited."""

    reason: str = "final"


AgentEvent = (
    TextDelta
    | AgentStatus
    | ToolStarted
    | ToolFinished
    | ConfirmationRequired
    | AgentError
    | UserQuestionRequested
    | TurnCancelled
    | TurnComplete
)


@dataclass
class ModelStep:
    text: str
    tool_calls: list[ToolCall]


def tool_call_id(tool_call: ToolCall, fallback_index: int) -> str:
    if tool_call.id:
        return tool_call.id
    return f"{tool_call.name}_{fallback_index}"


def tool_call_payload(tool_call: ToolCall, fallback_index: int) -> dict[str, Any]:
    return {
        "id": tool_call_id(tool_call, fallback_index),
        "name": tool_call.name,
        "arguments": dict(tool_call.arguments),
    }


class SingleToolAgent:
    """Chapter 4 Agent Loop.

    The class name is kept for compatibility with earlier chapters and tests, but
    the behavior is now a multi-step ReAct loop.
    """

    def __init__(
        self,
        provider: ChatProvider,
        registry: ToolRegistry,
        context: ToolContext,
        max_tool_steps: int = DEFAULT_MAX_TOOL_STEPS,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.context = context
        self.max_tool_steps = max_tool_steps
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def reset_cancel(self) -> None:
        self._cancel_requested = False

    def run_turn(self, session: ChatSession, user_text: str, mode: AgentMode = "normal") -> AgentTurnResult:
        events = list(self.stream_turn(session, user_text, mode=mode))
        tool_calls = [event.tool_call for event in events if isinstance(event, ToolFinished)]
        tool_results = [event.result for event in events if isinstance(event, ToolFinished)]
        stop_reason = "final"
        for event in reversed(events):
            if isinstance(event, TurnComplete):
                stop_reason = event.reason
                break
            if isinstance(event, TurnCancelled):
                stop_reason = event.reason
                break
            if isinstance(event, AgentError):
                stop_reason = "error"
                break
        final_text = ""
        for message in reversed(session.messages):
            if message.get("role") == "assistant" and "content" in message:
                final_text = str(message.get("content") or "")
                break
        return AgentTurnResult(
            final_text=final_text,
            tool_call=tool_calls[0] if tool_calls else None,
            tool_result=tool_results[0] if tool_results else None,
            tool_calls=tool_calls,
            tool_results=tool_results,
            stop_reason=stop_reason,
        )

    def confirm_pending(self, session: ChatSession, pending: PendingToolRequest) -> AgentTurnResult:
        result_payload = self._tool_result_for_call(pending.tool_call, mode="normal")
        session.add_tool_result(pending.tool_call.name, result_payload, tool_id=tool_call_id(pending.tool_call, 0))
        turn_result = self.run_turn(session, "", mode="normal")
        turn_result.tool_call = pending.tool_call
        turn_result.tool_result = result_payload
        turn_result.tool_calls = [pending.tool_call, *turn_result.tool_calls]
        turn_result.tool_results = [result_payload, *turn_result.tool_results]
        return turn_result

    def deny_pending(self, session: ChatSession, pending: PendingToolRequest) -> AgentTurnResult:
        result_payload = {
            "ok": False,
            "content": "",
            "error": f"User denied execution of tool {pending.tool_call.name}.",
            "metadata": {"denied": True, "tool_name": pending.tool_call.name},
        }
        session.add_tool_result(pending.tool_call.name, result_payload, tool_id=tool_call_id(pending.tool_call, 0))
        turn_result = self.run_turn(session, "", mode="normal")
        turn_result.tool_call = pending.tool_call
        turn_result.tool_result = result_payload
        turn_result.tool_calls = [pending.tool_call, *turn_result.tool_calls]
        turn_result.tool_results = [result_payload, *turn_result.tool_results]
        return turn_result

    def stream_turn(
        self,
        session: ChatSession,
        user_text: str,
        mode: AgentMode = "normal",
    ) -> Iterator[AgentEvent]:
        self.reset_cancel()
        if user_text:
            session.add_user_message(self._user_prompt(user_text, mode))
        executed_steps = 0
        tool_definitions = self.registry.list_definitions()

        while executed_steps < self.max_tool_steps:
            if self._cancel_requested:
                yield TurnCancelled()
                return

            yield AgentStatus("Thinking")
            try:
                step = yield from self._collect_model_step(session, tool_definitions)
            except Exception as exc:
                yield AgentError(str(exc))
                yield TurnComplete("error")
                return
            if self._cancel_requested:
                yield TurnCancelled()
                return

            if not step.tool_calls:
                final_text = step.text or "(模型未返回文本)"
                if not step.text:
                    yield TextDelta(final_text)
                session.add_assistant_message(final_text)
                yield TurnComplete("final")
                return

            self._ensure_tool_call_ids(step.tool_calls)
            remaining = self.max_tool_steps - executed_steps
            tool_calls = step.tool_calls[:remaining]
            session.add_tool_calls([tool_call_payload(tool_call, index) for index, tool_call in enumerate(tool_calls)])

            results = yield from self._execute_tool_calls(tool_calls, mode)
            for index, (tool_call, result) in enumerate(zip(tool_calls, results)):
                session.add_tool_result(tool_call.name, result, tool_id=tool_call_id(tool_call, index))
            executed_steps += len(tool_calls)

            question_event = self._question_event(tool_calls, results)
            if question_event is not None:
                yield question_event
                yield TurnComplete("await_user")
                return

            if len(step.tool_calls) > len(tool_calls) or executed_steps >= self.max_tool_steps:
                message = f"Reached maximum tool steps ({self.max_tool_steps})."
                session.add_assistant_message(message)
                yield TextDelta(message)
                yield TurnComplete("max_steps")
                return

        message = f"Reached maximum tool steps ({self.max_tool_steps})."
        session.add_assistant_message(message)
        yield TextDelta(message)
        yield TurnComplete("max_steps")

    def stream_confirm(self, session: ChatSession, pending: PendingToolRequest) -> Iterator[AgentEvent]:
        yield ToolStarted(pending.tool_call)
        result = self._tool_result_for_call(pending.tool_call, mode="normal")
        session.add_tool_result(pending.tool_call.name, result, tool_id=tool_call_id(pending.tool_call, 0))
        yield ToolFinished(pending.tool_call, result)
        yield from self.stream_turn(session, "", mode="normal")

    def stream_deny(self, session: ChatSession, pending: PendingToolRequest) -> Iterator[AgentEvent]:
        result = {
            "ok": False,
            "content": "",
            "error": f"User denied execution of tool {pending.tool_call.name}.",
            "metadata": {"denied": True, "tool_name": pending.tool_call.name},
        }
        session.add_tool_result(pending.tool_call.name, result, tool_id=tool_call_id(pending.tool_call, 0))
        yield ToolFinished(pending.tool_call, result)
        yield from self.stream_turn(session, "", mode="normal")

    def _collect_model_step(self, session: ChatSession, tool_definitions: list[dict[str, Any]]) -> Iterator[AgentEvent | ModelStep]:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for chunk in self._stream_provider_response(session.snapshot(), tools=tool_definitions):
            if self._cancel_requested:
                return ModelStep("".join(text_parts), tool_calls)
            if chunk.text:
                text_parts.append(chunk.text)
                yield TextDelta(chunk.text)
            if chunk.tool_calls:
                tool_calls.extend(chunk.tool_calls)
            elif chunk.tool_call is not None:
                tool_calls.append(chunk.tool_call)
        return ModelStep("".join(text_parts), self._dedupe_tool_calls(tool_calls))

    def _stream_provider_response(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Iterator[StreamChunk]:
        stream_response = getattr(self.provider, "stream_response", None)
        if stream_response is not None:
            yield from stream_response(messages, tools=tools)
            return
        response: ChatResponse = self.provider.complete_chat(messages, tools=tools)
        if response.tool_calls:
            yield StreamChunk(tool_calls=response.tool_calls)
        elif response.text:
            yield StreamChunk(text=response.text)

    def _execute_tool_calls(self, tool_calls: list[ToolCall], mode: AgentMode) -> Iterator[AgentEvent | list[dict[str, Any]]]:
        safe_calls, unsafe_calls = self.partition_tool_calls(tool_calls)
        results_by_id: dict[str, dict[str, Any]] = {}

        if safe_calls:
            for tool_call in safe_calls:
                yield ToolStarted(tool_call)
            with ThreadPoolExecutor(max_workers=len(safe_calls)) as executor:
                futures = {
                    tool_call_id(tool_call, index): executor.submit(self._tool_result_for_call, tool_call, mode)
                    for index, tool_call in enumerate(safe_calls)
                }
                for index, tool_call in enumerate(safe_calls):
                    if self._cancel_requested:
                        break
                    result = futures[tool_call_id(tool_call, index)].result()
                    results_by_id[tool_call_id(tool_call, index)] = result
                    yield ToolFinished(tool_call, result)

        for index, tool_call in enumerate(unsafe_calls):
            if self._cancel_requested:
                break
            yield ToolStarted(tool_call)
            result = self._tool_result_for_call(tool_call, mode)
            results_by_id[tool_call_id(tool_call, index)] = result
            yield ToolFinished(tool_call, result)

        ordered_results = [
            results_by_id.get(tool_call_id(tool_call, index), self._cancelled_tool_result(tool_call))
            for index, tool_call in enumerate(tool_calls)
        ]
        return ordered_results

    def partition_tool_calls(self, tool_calls: list[ToolCall]) -> tuple[list[ToolCall], list[ToolCall]]:
        safe: list[ToolCall] = []
        unsafe: list[ToolCall] = []
        for tool_call in tool_calls:
            try:
                if self.registry.requires_confirmation(tool_call.name):
                    unsafe.append(tool_call)
                else:
                    safe.append(tool_call)
            except ToolError:
                unsafe.append(tool_call)
        return safe, unsafe

    def _tool_result_for_call(self, tool_call: ToolCall, mode: AgentMode = "normal") -> dict[str, Any]:
        try:
            tool = self.registry.get(tool_call.name)
        except ToolError as exc:
            return {"ok": False, "error": str(exc), "content": "", "metadata": {}}

        if mode == "plan" and tool.definition.requires_confirmation:
            return {
                "ok": False,
                "content": "",
                "error": f"Plan Mode blocked unsafe tool: {tool_call.name}",
                "metadata": {"blocked_by_plan_mode": True, "tool_name": tool_call.name},
            }

        missing = [name for name in tool.definition.schema.required if name not in tool_call.arguments]
        if missing:
            return {
                "ok": False,
                "content": "",
                "error": f"Missing required arguments: {', '.join(missing)}",
                "metadata": {"missing_arguments": missing},
            }
        try:
            result = tool.execute(tool_call.arguments, self.context)
        except ToolError as exc:
            return {"ok": False, "error": str(exc), "content": "", "metadata": {}}
        return result.to_message_content()

    def _cancelled_tool_result(self, tool_call: ToolCall) -> dict[str, Any]:
        return {
            "ok": False,
            "content": "",
            "error": f"Cancelled before tool completed: {tool_call.name}",
            "metadata": {"cancelled": True, "tool_name": tool_call.name},
        }

    def _question_event(
        self,
        tool_calls: list[ToolCall],
        results: list[dict[str, Any]],
    ) -> UserQuestionRequested | None:
        for tool_call, result in zip(tool_calls, results):
            metadata = result.get("metadata") or {}
            if not metadata.get("await_user"):
                continue
            question = str(metadata.get("question") or result.get("content") or "")
            options = metadata.get("options") or []
            if not isinstance(options, list):
                options = []
            questions = self._clarification_questions_from_metadata(metadata)
            return UserQuestionRequested(
                tool_call=tool_call,
                question=question,
                options=[str(option) for option in options],
                reason=str(metadata.get("reason") or ""),
                questions=questions,
            )
        return None

    def _clarification_questions_from_metadata(self, metadata: dict[str, Any]) -> list[ClarificationQuestion]:
        raw_questions = metadata.get("questions")
        if not isinstance(raw_questions, list):
            return []

        questions: list[ClarificationQuestion] = []
        for index, raw_question in enumerate(raw_questions, start=1):
            if not isinstance(raw_question, dict):
                prompt = str(raw_question).strip()
                if not prompt:
                    continue
                questions.append(
                    ClarificationQuestion(
                        id=f"question_{index}",
                        title=f"Question {index}",
                        question=prompt,
                    )
                )
                continue

            prompt = str(raw_question.get("question") or "").strip()
            if not prompt:
                continue
            question_id = str(raw_question.get("id") or f"question_{index}").strip() or f"question_{index}"
            title = str(raw_question.get("title") or question_id or f"Question {index}").strip()
            questions.append(
                ClarificationQuestion(
                    id=question_id,
                    title=title or f"Question {index}",
                    question=prompt,
                    options=self._question_options_from_metadata(raw_question.get("options")),
                )
            )
        return questions

    def _question_options_from_metadata(self, raw_options: Any) -> list[QuestionOption]:
        if not isinstance(raw_options, list):
            return []
        options: list[QuestionOption] = []
        for raw_option in raw_options:
            if isinstance(raw_option, dict):
                label = str(raw_option.get("label") or "").strip()
                if not label:
                    continue
                options.append(
                    QuestionOption(
                        label=label,
                        description=str(raw_option.get("description") or "").strip(),
                        recommended=bool(raw_option.get("recommended")),
                        allow_custom_input=bool(raw_option.get("allow_custom_input")),
                    )
                )
                continue
            label = str(raw_option).strip()
            if label:
                options.append(QuestionOption(label=label))
        return options

    def _dedupe_tool_calls(self, tool_calls: list[ToolCall]) -> list[ToolCall]:
        unique: list[ToolCall] = []
        seen: set[tuple[str, str, str | None]] = set()
        for tool_call in tool_calls:
            key = (tool_call.name, repr(sorted(tool_call.arguments.items())), tool_call.id)
            if key in seen:
                continue
            seen.add(key)
            unique.append(tool_call)
        return unique

    def _ensure_tool_call_ids(self, tool_calls: list[ToolCall]) -> None:
        for index, tool_call in enumerate(tool_calls):
            if tool_call.id is None:
                tool_call.id = f"{tool_call.name}_{index}"

    def _user_prompt(self, user_text: str, mode: AgentMode) -> str:
        if mode == "plan":
            return f"{PLAN_MODE_PREFIX}{user_text}"
        return user_text
