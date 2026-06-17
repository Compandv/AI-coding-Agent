from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

from mewcode.context import (
    ContextChunkSummaryFinished,
    ContextChunkSummaryStarted,
    ContextCompressionFallbackUsed,
    ContextCompressionFailed,
    ContextCompressionFinished,
    ContextCompressionSkipped,
    ContextCompressionStarted,
    ContextEmergencyRetry,
    ContextManager,
    ContextStatsReported,
)
from mewcode.memory import MemoryContextManager
from mewcode.permissions import ConfirmScope, PermissionChecker, PermissionDecision
from mewcode.prompts import PromptPayload, assemble_api_payload
from mewcode.providers.base import ChatProvider, ChatResponse, ProviderUsage, StreamChunk, ToolCall
from mewcode.providers.errors import ProviderError
from mewcode.session import ChatSession
from mewcode.skills import SkillManager
from mewcode.tools import ToolContext, ToolError, ToolRegistry


AgentMode = Literal["normal", "plan"]
DEFAULT_MAX_TOOL_STEPS = 24


@dataclass
class PendingToolRequest:
    tool_call: ToolCall
    decision: PermissionDecision | None = None


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
class ToolResultSpilled:
    """A tool result was replaced by a preview and stored on disk."""

    tool_call: ToolCall
    count: int = 1
    freed_chars: int = 0
    stored_path: str = ""


@dataclass
class ConfirmationRequired:
    """Compatibility event retained from chapter 3; not emitted by chapter 4 normal flow."""

    pending_request: PendingToolRequest


@dataclass
class AgentError:
    message: str


@dataclass
class PromptUsageObserved:
    usage: ProviderUsage


@dataclass
class MemoryUpdated:
    count: int = 0


@dataclass
class MemoryCommandResult:
    content: str


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
    | ToolResultSpilled
    | ConfirmationRequired
    | AgentError
    | PromptUsageObserved
    | ContextCompressionStarted
    | ContextCompressionFinished
    | ContextCompressionFailed
    | ContextCompressionFallbackUsed
    | ContextChunkSummaryStarted
    | ContextChunkSummaryFinished
    | ContextStatsReported
    | ContextCompressionSkipped
    | ContextEmergencyRetry
    | MemoryUpdated
    | MemoryCommandResult
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
        permission_checker: PermissionChecker | None = None,
        context_manager: ContextManager | None = None,
        memory_manager: MemoryContextManager | None = None,
        skill_manager: SkillManager | None = None,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.context = context
        self.max_tool_steps = max_tool_steps
        self.permission_checker = permission_checker
        self.context_manager = context_manager
        self.memory_manager = memory_manager
        self.skill_manager = skill_manager
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def reset_cancel(self) -> None:
        self._cancel_requested = False

    def run_turn(self, session: ChatSession, user_text: str, mode: AgentMode = "normal") -> AgentTurnResult:
        history_start = len(session.messages)
        events = list(self.stream_turn(session, user_text, mode=mode))
        tool_calls = [event.tool_call for event in events if isinstance(event, ToolFinished)]
        tool_results = [event.result for event in events if isinstance(event, ToolFinished)]
        ordered_tool_calls, ordered_tool_results = self._turn_tool_history(session, history_start)
        if ordered_tool_calls or ordered_tool_results:
            tool_calls = ordered_tool_calls
            tool_results = ordered_tool_results
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

    def _turn_tool_history(self, session: ChatSession, history_start: int) -> tuple[list[ToolCall], list[dict[str, Any]]]:
        new_messages = session.messages[history_start:]
        ordered_tool_calls: list[ToolCall] = []
        ordered_tool_results: list[dict[str, Any]] = []

        for message in new_messages:
            if message.get("role") == "assistant" and message.get("tool_calls"):
                for payload in message.get("tool_calls") or []:
                    if not isinstance(payload, dict):
                        continue
                    call_id = str(payload.get("id") or "")
                    tool_call = ToolCall(
                        name=str(payload.get("name") or ""),
                        arguments=dict(payload.get("arguments") or {}),
                        id=call_id or None,
                    )
                    ordered_tool_calls.append(tool_call)
                continue
            if message.get("role") != "tool":
                continue
            result = message.get("tool_result")
            if isinstance(result, dict):
                ordered_tool_results.append(result)
        return ordered_tool_calls, ordered_tool_results

    def confirm_pending(
        self,
        session: ChatSession,
        pending: PendingToolRequest,
        scope: ConfirmScope = "once",
    ) -> AgentTurnResult:
        result_payload = self._confirm_tool_result(pending, scope=scope)
        result_payload = self._process_tool_result(session, pending.tool_call, result_payload, tool_call_id(pending.tool_call, 0))
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
        result_payload = self._process_tool_result(session, pending.tool_call, result_payload, tool_call_id(pending.tool_call, 0))
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
        skill_names: list[str] | None = None,
        skill_arguments: str = "",
    ) -> Iterator[AgentEvent]:
        self.reset_cancel()
        if user_text:
            session.add_user_message(user_text)
        executed_steps = 0
        model_request_index = 0
        allow_plan_file_write = self._allows_plan_file_write(user_text)
        while True:
            if self._cancel_requested:
                yield TurnCancelled()
                return

            model_request_index += 1
            try:
                tool_definitions = self._tool_definitions_for_skills(skill_names)
                if self.context_manager is not None:
                    start_event = self.context_manager.prepare_start_event(
                        session,
                        tool_definitions,
                        mode=mode,
                        model_request_index=model_request_index,
                    )
                    if start_event is not None:
                        yield start_event
                    context_result = self.context_manager.prepare_before_request(
                        session,
                        tool_definitions,
                        mode=mode,
                        model_request_index=model_request_index,
                        emit_started=start_event is None,
                    )
                    yield from context_result.events
                    if self._cancel_requested:
                        yield TurnCancelled()
                        return
                yield AgentStatus("Thinking")
                prompt_payload = self._prompt_payload(
                    session,
                    tool_definitions,
                    mode,
                    model_request_index,
                    skill_names=skill_names,
                    skill_arguments=skill_arguments,
                )
                try:
                    step = yield from self._collect_model_step(session, prompt_payload)
                except Exception as exc:
                    if self.context_manager is None or not self.context_manager.is_context_length_error(exc):
                        raise
                    emergency_result = self.context_manager.compact(
                        session,
                        tool_definitions=tool_definitions,
                        kind="emergency",
                        mode=mode,
                        model_request_index=model_request_index,
                        bypass_breaker=True,
                    )
                    yield from emergency_result.events
                    if not emergency_result.compacted:
                        raise
                    yield ContextEmergencyRetry(str(exc))
                    prompt_payload = self._prompt_payload(
                        session,
                        tool_definitions,
                        mode,
                        model_request_index,
                        skill_names=skill_names,
                        skill_arguments=skill_arguments,
                    )
                    step = yield from self._collect_model_step(session, prompt_payload)
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
                memory_count = self._remember_completed_turn(session)
                if memory_count:
                    yield MemoryUpdated(memory_count)
                yield TurnComplete("final")
                return

            self._ensure_tool_call_ids(step.tool_calls)
            if executed_steps >= self.max_tool_steps:
                message = f"Reached maximum tool steps ({self.max_tool_steps})."
                session.add_assistant_message(message)
                yield TextDelta(message)
                yield TurnComplete("max_steps")
                return

            tool_calls = step.tool_calls
            session.add_tool_calls([tool_call_payload(tool_call, index) for index, tool_call in enumerate(tool_calls)])

            confirmation = self._permission_confirmation(
                tool_calls,
                mode,
                allow_plan_file_write,
                turn_skill_names=skill_names,
            )
            if confirmation is not None:
                yield confirmation
                yield TurnComplete("await_user")
                return

            results = yield from self._execute_tool_calls(
                session,
                tool_calls,
                mode,
                allow_plan_file_write=allow_plan_file_write,
                turn_skill_names=skill_names,
            )
            for index, (tool_call, result) in enumerate(zip(tool_calls, results)):
                self._sync_dynamic_tool_permissions(result)
                session.add_tool_result(tool_call.name, result, tool_id=tool_call_id(tool_call, index))
            executed_steps += 1

            question_event = self._question_event(tool_calls, results)
            if question_event is not None:
                yield question_event
                yield TurnComplete("await_user")
                return


    def stream_skill_command(
        self,
        session: ChatSession,
        skill_name: str,
        arguments: str = "",
        mode: AgentMode = "normal",
    ) -> Iterator[AgentEvent]:
        if self.skill_manager is None:
            yield AgentError("Skill system is not configured.")
            yield TurnComplete("error")
            return
        skill = self.skill_manager.get(skill_name)
        if skill is None:
            yield AgentError(f"Unknown skill: {skill_name}")
            yield TurnComplete("error")
            return

        prompt = skill.render(arguments)
        if skill.mode == "inline":
            yield from self.stream_turn(
                session,
                prompt,
                mode=mode,
                skill_names=[skill.name],
                skill_arguments=arguments,
            )
            return

        session.add_user_message(prompt)
        fork_session = self._fork_session(session, skill.history)
        final_text = ""
        for event in self.stream_turn(
            fork_session,
            prompt,
            mode=mode,
            skill_names=[skill.name],
            skill_arguments=arguments,
        ):
            if isinstance(event, TextDelta):
                final_text += event.text
            yield event
        if not final_text:
            for message in reversed(fork_session.messages):
                if message.get("role") == "assistant" and "content" in message:
                    final_text = str(message.get("content") or "")
                    break
        if final_text:
            session.add_assistant_message(final_text)

    def _fork_session(self, session: ChatSession, history: str) -> ChatSession:
        if history == "none":
            messages = []
        elif history == "full":
            messages = session.snapshot()[:-1]
        else:
            messages = session.snapshot()[-9:-1]
        return ChatSession(messages=messages)

    def stream_confirm(
        self,
        session: ChatSession,
        pending: PendingToolRequest,
        scope: ConfirmScope = "once",
    ) -> Iterator[AgentEvent]:
        yield ToolStarted(pending.tool_call)
        result = self._confirm_tool_result(pending, scope=scope)
        result = self._process_tool_result(session, pending.tool_call, result, tool_call_id(pending.tool_call, 0))
        session.add_tool_result(pending.tool_call.name, result, tool_id=tool_call_id(pending.tool_call, 0))
        yield from self._tool_finished_events(pending.tool_call, result)
        yield from self.stream_turn(session, "", mode="normal")

    def stream_deny(self, session: ChatSession, pending: PendingToolRequest) -> Iterator[AgentEvent]:
        result = {
            "ok": False,
            "content": "",
            "error": f"User denied execution of tool {pending.tool_call.name}.",
            "metadata": {"denied": True, "tool_name": pending.tool_call.name},
        }
        result = self._process_tool_result(session, pending.tool_call, result, tool_call_id(pending.tool_call, 0))
        session.add_tool_result(pending.tool_call.name, result, tool_id=tool_call_id(pending.tool_call, 0))
        yield from self._tool_finished_events(pending.tool_call, result)
        yield from self.stream_turn(session, "", mode="normal")

    def stream_compact(self, session: ChatSession, focus: str = "") -> Iterator[AgentEvent]:
        if self.context_manager is None:
            yield ContextCompressionSkipped(kind="manual", reason="context_manager_not_configured", before_tokens=0)
            yield TurnComplete("compact_skipped")
            return
        tool_definitions = self.registry.list_definitions()
        start_event = self.context_manager.compact_start_event(session, tool_definitions, kind="manual")
        if start_event is not None:
            yield start_event
        result = self.context_manager.compact(
            session,
            tool_definitions=tool_definitions,
            kind="manual",
            focus=focus,
            bypass_breaker=True,
            emit_started=start_event is None,
        )
        yield from result.events
        if result.failed:
            yield TurnComplete("compact_failed")
        elif result.skipped:
            yield TurnComplete("compact_skipped")
        else:
            yield TurnComplete("compact")

    def stream_context_stats(self, session: ChatSession, mode: AgentMode = "normal") -> Iterator[AgentEvent]:
        if self.context_manager is None:
            yield ContextCompressionSkipped(kind="manual", reason="context_manager_not_configured", before_tokens=0)
            yield TurnComplete("context_skipped")
            return
        yield self.context_manager.report_stats(
            session,
            self.registry.list_definitions(),
            mode=mode,
            model_request_index=0,
        )
        yield TurnComplete("context")

    def stream_memory_command(self, session: ChatSession, text: str) -> Iterator[AgentEvent]:
        if self.memory_manager is None:
            yield MemoryCommandResult("Memory system is not configured.")
            yield TurnComplete("memory")
            return
        result = self.memory_manager.command(text, session) or "Unknown memory/session command."
        yield MemoryCommandResult(result)
        yield TurnComplete("memory")

    def _collect_model_step(self, session: ChatSession, prompt_payload: PromptPayload) -> Iterator[AgentEvent | ModelStep]:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        try:
            for chunk in self._stream_provider_response(prompt_payload):
                if self._cancel_requested:
                    return ModelStep("".join(text_parts), tool_calls)
                if chunk.text:
                    text_parts.append(chunk.text)
                    yield TextDelta(chunk.text)
                if chunk.usage is not None:
                    if self.context_manager is not None:
                        self.context_manager.record_usage(session, chunk.usage)
                    yield PromptUsageObserved(chunk.usage)
                if chunk.tool_calls:
                    tool_calls.extend(chunk.tool_calls)
                elif chunk.tool_call is not None:
                    tool_calls.append(chunk.tool_call)
        except ProviderError:
            if text_parts or tool_calls:
                raise
            response = self.provider.complete_chat(prompt_payload, tools=prompt_payload.tools)
            if response.text:
                text_parts.append(response.text)
                yield TextDelta(response.text)
            if response.usage is not None:
                if self.context_manager is not None:
                    self.context_manager.record_usage(session, response.usage)
                yield PromptUsageObserved(response.usage)
            tool_calls.extend(response.tool_calls)
        return ModelStep("".join(text_parts), self._dedupe_tool_calls(tool_calls))

    def _stream_provider_response(
        self,
        prompt_payload: PromptPayload,
    ) -> Iterator[StreamChunk]:
        stream_response = getattr(self.provider, "stream_response", None)
        if stream_response is not None:
            yield from stream_response(prompt_payload, tools=prompt_payload.tools)
            return
        response: ChatResponse = self.provider.complete_chat(prompt_payload, tools=prompt_payload.tools)
        if response.tool_calls:
            yield StreamChunk(tool_calls=response.tool_calls, usage=response.usage)
        elif response.text:
            yield StreamChunk(text=response.text, usage=response.usage)
        elif response.usage is not None:
            yield StreamChunk(usage=response.usage)

    def _execute_tool_calls(
        self,
        session: ChatSession,
        tool_calls: list[ToolCall],
        mode: AgentMode,
        allow_plan_file_write: bool = False,
        turn_skill_names: list[str] | None = None,
    ) -> Iterator[AgentEvent | list[dict[str, Any]]]:
        safe_calls, unsafe_calls = self.partition_tool_calls(tool_calls)
        results_by_id: dict[str, dict[str, Any]] = {}
        original_indexes = {id(tool_call): index for index, tool_call in enumerate(tool_calls)}

        if safe_calls:
            for tool_call in safe_calls:
                yield ToolStarted(tool_call)
            with ThreadPoolExecutor(max_workers=len(safe_calls)) as executor:
                futures = {
                    tool_call_id(tool_call, original_indexes[id(tool_call)]): executor.submit(
                        self._tool_result_for_call,
                        tool_call,
                        mode,
                        allow_plan_file_write,
                        False,
                        turn_skill_names,
                    )
                    for tool_call in safe_calls
                }
                for tool_call in safe_calls:
                    if self._cancel_requested:
                        break
                    result = futures[tool_call_id(tool_call, original_indexes[id(tool_call)])].result()
                    result = self._process_tool_result(
                        session,
                        tool_call,
                        result,
                        tool_call_id(tool_call, original_indexes[id(tool_call)]),
                    )
                    results_by_id[tool_call_id(tool_call, original_indexes[id(tool_call)])] = result
                    yield from self._tool_finished_events(tool_call, result)

        for tool_call in unsafe_calls:
            if self._cancel_requested:
                break
            yield ToolStarted(tool_call)
            result = self._tool_result_for_call(
                tool_call,
                mode,
                allow_plan_file_write,
                turn_skill_names=turn_skill_names,
            )
            result = self._process_tool_result(
                session,
                tool_call,
                result,
                tool_call_id(tool_call, original_indexes[id(tool_call)]),
            )
            results_by_id[tool_call_id(tool_call, original_indexes[id(tool_call)])] = result
            yield from self._tool_finished_events(tool_call, result)

        ordered_results = [
            results_by_id.get(tool_call_id(tool_call, index), self._cancelled_tool_result(tool_call))
            for index, tool_call in enumerate(tool_calls)
        ]
        return ordered_results

    def _process_tool_result(
        self,
        session: ChatSession,
        tool_call: ToolCall,
        result: dict[str, Any],
        tool_id: str | None = None,
    ) -> dict[str, Any]:
        if self.context_manager is None:
            return result
        return self.context_manager.process_tool_result(session, tool_call, result, tool_id)

    def _tool_finished_events(self, tool_call: ToolCall, result: dict[str, Any]) -> Iterator[AgentEvent]:
        yield ToolFinished(tool_call, result)
        spill_event = self._tool_result_spill_event(tool_call, result)
        if spill_event is not None:
            yield spill_event

    def _tool_result_spill_event(self, tool_call: ToolCall, result: dict[str, Any]) -> ToolResultSpilled | None:
        metadata = result.get("metadata") or {}
        if not metadata.get("stored_on_disk"):
            return None
        freed_chars = self._metadata_int(metadata, "spilled_freed_chars")
        if freed_chars <= 0:
            freed_chars = self._metadata_int(metadata, "original_result_chars")
        if freed_chars <= 0:
            freed_chars = self._metadata_int(metadata, "original_result_bytes")
        return ToolResultSpilled(
            tool_call=tool_call,
            count=1,
            freed_chars=max(0, freed_chars),
            stored_path=str(metadata.get("stored_path") or ""),
        )

    def _metadata_int(self, metadata: dict[str, Any], key: str) -> int:
        try:
            return int(metadata.get(key) or 0)
        except (TypeError, ValueError):
            return 0

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

    def _tool_result_for_call(
        self,
        tool_call: ToolCall,
        mode: AgentMode = "normal",
        allow_plan_file_write: bool = False,
        skip_permission: bool = False,
        turn_skill_names: list[str] | None = None,
    ) -> dict[str, Any]:
        if self.skill_manager is not None and not self.skill_manager.tool_allowed(tool_call.name, turn_skill_names):
            return {
                "ok": False,
                "content": "",
                "error": f"Skill tool whitelist blocked tool: {tool_call.name}",
                "metadata": {
                    "blocked_by_skill": True,
                    "tool_name": tool_call.name,
                    "active_skills": list(self.skill_manager.active_skill_names),
                    "turn_skills": list(turn_skill_names or []),
                },
            }
        try:
            tool = self.registry.get(tool_call.name)
        except ToolError as exc:
            return {"ok": False, "error": str(exc), "content": "", "metadata": {}}

        if mode == "plan" and tool_call.name == "WritePlanFile" and not allow_plan_file_write:
            return {
                "ok": False,
                "content": "",
                "error": "Plan Mode only saves a plan file when the user explicitly asks for one.",
                "metadata": {
                    "blocked_by_plan_mode": True,
                    "tool_name": tool_call.name,
                    "requires_explicit_plan_file": True,
                },
            }

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

        if self.permission_checker is not None and not skip_permission:
            decision = self.permission_checker.check(tool_call)
            if decision.action == "deny":
                return self._permission_result(tool_call, decision)
            if decision.action == "ask":
                return self._permission_result(tool_call, decision)
        try:
            result = tool.execute(tool_call.arguments, self.context)
        except ToolError as exc:
            return {"ok": False, "error": str(exc), "content": "", "metadata": {"tool_name": tool_call.name}}
        except Exception as exc:
            return {
                "ok": False,
                "error": f"Tool execution failed: {exc}",
                "content": "",
                "metadata": {"tool_name": tool_call.name, "unexpected_tool_error": True},
            }
        return result.to_message_content()

    def _confirm_tool_result(self, pending: PendingToolRequest, scope: ConfirmScope = "once") -> dict[str, Any]:
        if scope == "permanent" and self.permission_checker is not None:
            self.permission_checker.allow_permanently(pending.tool_call)
        return self._tool_result_for_call(pending.tool_call, mode="normal", skip_permission=True)

    def _permission_confirmation(
        self,
        tool_calls: list[ToolCall],
        mode: AgentMode,
        allow_plan_file_write: bool,
        turn_skill_names: list[str] | None = None,
    ) -> ConfirmationRequired | None:
        if self.permission_checker is None:
            return None
        for tool_call in tool_calls:
            if self.skill_manager is not None and not self.skill_manager.tool_allowed(tool_call.name, turn_skill_names):
                continue
            if self._plan_mode_blocks(tool_call, mode, allow_plan_file_write):
                continue
            try:
                tool = self.registry.get(tool_call.name)
            except ToolError:
                continue
            missing = [name for name in tool.definition.schema.required if name not in tool_call.arguments]
            if missing:
                continue
            decision = self.permission_checker.check(tool_call)
            if decision.action == "ask":
                return ConfirmationRequired(PendingToolRequest(tool_call=tool_call, decision=decision))
        return None

    def _permission_result(self, tool_call: ToolCall, decision: PermissionDecision) -> dict[str, Any]:
        metadata = {
            "blocked_by_permission": decision.action != "allow",
            "permission_action": decision.action,
            "permission_reason": decision.reason,
            "tool_name": tool_call.name,
            **decision.metadata,
        }
        if decision.rule is not None:
            metadata["permission_rule"] = decision.rule.expression
            metadata["permission_rule_source"] = decision.rule.source
        return {"ok": False, "content": "", "error": decision.reason, "metadata": metadata}

    def _sync_dynamic_tool_permissions(self, result: dict[str, Any]) -> None:
        if self.permission_checker is None:
            return
        metadata = result.get("metadata") or {}
        activated_tools = metadata.get("activated_read_tools")
        if not isinstance(activated_tools, list):
            return
        read_tools = {str(tool_name) for tool_name in activated_tools if isinstance(tool_name, str)}
        if read_tools:
            self.permission_checker.add_read_tools(read_tools)

    def _plan_mode_blocks(self, tool_call: ToolCall, mode: AgentMode, allow_plan_file_write: bool) -> bool:
        if mode != "plan":
            return False
        if tool_call.name == "WritePlanFile" and not allow_plan_file_write:
            return True
        try:
            tool = self.registry.get(tool_call.name)
        except ToolError:
            return False
        return tool.definition.requires_confirmation

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

    def _prompt_payload(
        self,
        session: ChatSession,
        tool_definitions: list[dict[str, Any]],
        mode: AgentMode,
        model_request_index: int,
        skill_names: list[str] | None = None,
        skill_arguments: str = "",
    ) -> PromptPayload:
        overlay_messages = self.memory_manager.overlay_messages() if self.memory_manager is not None else []
        if self.skill_manager is not None:
            overlay_messages = [
                *overlay_messages,
                *self.skill_manager.overlay_messages(skill_names, arguments=skill_arguments),
            ]
        payload = assemble_api_payload(
            session_messages=session.snapshot(),
            tools=tool_definitions,
            root_dir=self.context.root_dir,
            mode=mode,
            model_request_index=model_request_index,
            overlay_messages=overlay_messages,
        )
        if self.memory_manager is not None:
            payload.metadata["memory_context"] = self.memory_manager.status_counts()
        if self.skill_manager is not None:
            payload.metadata["active_skills"] = list(self.skill_manager.active_skill_names)
            payload.metadata["turn_skills"] = list(skill_names or [])
        return payload

    def _tool_definitions_for_skills(self, turn_skill_names: list[str] | None = None) -> list[dict[str, Any]]:
        definitions = self.registry.list_definitions()
        if self.skill_manager is None:
            return definitions
        return self.skill_manager.filter_tool_definitions(definitions, turn_skill_names)

    def _remember_completed_turn(self, session: ChatSession) -> int:
        if self.memory_manager is None:
            return 0
        try:
            return self.memory_manager.remember_turn(session)
        except Exception:
            return 0

    def _allows_plan_file_write(self, user_text: str) -> bool:
        normalized = user_text.lower()
        markers = [
            "writeplanfile",
            "plan file",
            "save the plan",
            "save plan",
            "write the plan",
            "保存计划",
            "保存成计划",
            "保存为计划",
            "写计划文件",
            "生成计划文件",
            "落盘",
        ]
        return any(marker in normalized for marker in markers)
