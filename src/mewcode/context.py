from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from mewcode.compact.const import (
    AUTO_SAFETY_MARGIN,
    MANUAL_SAFETY_MARGIN,
    MAX_CONSECUTIVE_AUTO_COMPACT_FAILURES,
    MESSAGE_AGGREGATE_LIMIT,
    COMPACT_FOCUS_MAX_CHARS,
    PREVIEW_HEAD_BYTES,
    PREVIEW_TAIL_BYTES,
    RECENT_KEEP_MESSAGES,
    RECENT_KEEP_TOKENS,
    SINGLE_RESULT_LIMIT,
    SUMMARY_CHUNK_MAX_TOKENS,
    SUMMARY_CHUNK_TARGET_TOKENS,
    SUMMARY_RESERVE,
)
from mewcode.compact.layer1 import result_size as compact_result_size
from mewcode.compact.layer1 import safe_filename as compact_safe_filename
from mewcode.compact.layer1 import spill_tool_result
from mewcode.compact.recovery import BOUNDARY_NOTICE
from mewcode.compact.state import ContentReplacementState, SessionContext
from mewcode.compact.summary_prompt import build_summary_prompt, extract_summary
from mewcode.compact.token import usage_anchor
from mewcode.prompts import CachePolicy, PromptPayload, assemble_api_payload
from mewcode.session import ChatSession, Message

if TYPE_CHECKING:
    from mewcode.providers.base import ChatProvider, ProviderUsage, ToolCall


CompactKind = Literal["auto", "manual", "emergency"]


@dataclass(frozen=True)
class ContextConfig:
    context_window_tokens: int = 128000
    auto_margin_tokens: int = AUTO_SAFETY_MARGIN
    manual_margin_tokens: int = MANUAL_SAFETY_MARGIN
    recent_token_target: int = RECENT_KEEP_TOKENS
    min_recent_messages: int = RECENT_KEEP_MESSAGES
    single_result_token_threshold: int = 8000
    aggregate_result_token_threshold: int = 16000
    single_result_byte_threshold: int = SINGLE_RESULT_LIMIT
    aggregate_result_byte_threshold: int = MESSAGE_AGGREGATE_LIMIT
    preview_chars: int = PREVIEW_HEAD_BYTES
    tool_preview_head_chars: int = PREVIEW_HEAD_BYTES
    tool_preview_tail_chars: int = PREVIEW_TAIL_BYTES
    summary_chunk_target_tokens: int = SUMMARY_CHUNK_TARGET_TOKENS
    summary_chunk_max_tokens: int = SUMMARY_CHUNK_MAX_TOKENS
    compact_focus_max_chars: int = COMPACT_FOCUS_MAX_CHARS
    max_summary_failures: int = MAX_CONSECUTIVE_AUTO_COMPACT_FAILURES
    cache_dir: str = ".mewcode/sessions"


@dataclass
class ContextCompressionStarted:
    kind: CompactKind
    before_tokens: int


@dataclass
class ContextCompressionFinished:
    kind: CompactKind
    before_tokens: int
    after_tokens: int
    reduced_tokens: int
    summary_tokens: int = 0
    summary_quality: str = "llm"


@dataclass
class ContextCompressionFailed:
    kind: CompactKind
    message: str
    consecutive_failures: int = 0


@dataclass
class ContextCompressionFallbackUsed:
    kind: CompactKind
    reason: str
    quality: str = "local"
    consecutive_failures: int = 0


@dataclass
class ContextChunkSummaryStarted:
    kind: CompactKind
    chunk_index: int
    chunk_count: int
    input_tokens: int


@dataclass
class ContextChunkSummaryFinished:
    kind: CompactKind
    chunk_index: int
    chunk_count: int
    output_tokens: int


@dataclass
class ContextStatsReported:
    estimated_tokens: int
    system_prompt_tokens: int
    tools_tokens: int
    user_history_tokens: int
    assistant_history_tokens: int
    tool_result_tokens: int
    compact_summary_tokens: int
    recent_raw_tokens: int
    auto_threshold_tokens: int
    context_window_tokens: int
    auto_compact_disabled: bool
    last_compaction_before_tokens: int = 0
    last_compaction_after_tokens: int = 0


@dataclass
class ContextCompressionSkipped:
    kind: CompactKind
    reason: str
    before_tokens: int


@dataclass
class ContextEmergencyRetry:
    reason: str


ContextEvent = (
    ContextCompressionStarted
    | ContextCompressionFinished
    | ContextCompressionFailed
    | ContextCompressionFallbackUsed
    | ContextChunkSummaryStarted
    | ContextChunkSummaryFinished
    | ContextStatsReported
    | ContextCompressionSkipped
    | ContextEmergencyRetry
)


@dataclass
class ContextOperationResult:
    events: list[ContextEvent] = field(default_factory=list)
    compacted: bool = False
    failed: bool = False
    skipped: bool = False


@dataclass
class ReadSnapshot:
    path: str
    preview: str
    stored_path: str = ""


@dataclass
class ContextSessionState:
    summary_failures: int = 0
    auto_compact_disabled: bool = False
    read_snapshots: dict[str, ReadSnapshot] = field(default_factory=dict)
    last_usage: ProviderUsage | None = None
    anchored_input_tokens: int | None = None
    anchored_message_count: int = 0
    replacement_state: ContentReplacementState = field(default_factory=ContentReplacementState)
    session_context: SessionContext | None = None
    last_compaction_before_tokens: int = 0
    last_compaction_after_tokens: int = 0


class TokenEstimator:
    """Fast approximate token estimator.

    The estimate intentionally favors stability over tokenizer precision. It is
    good enough for thresholding and can be anchored by provider usage.
    """

    def estimate_text(self, text: str) -> int:
        if not text:
            return 0
        ascii_chars = sum(1 for char in text if ord(char) < 128)
        non_ascii_chars = len(text) - ascii_chars
        return max(1, math.ceil(ascii_chars / 4) + math.ceil(non_ascii_chars / 2))

    def estimate_value(self, value: Any) -> int:
        if isinstance(value, str):
            return self.estimate_text(value)
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            text = str(value)
        return self.estimate_text(text)

    def estimate_message(self, message: Message) -> int:
        return self.estimate_value(message) + 4

    def estimate_messages(self, messages: list[Message]) -> int:
        return sum(self.estimate_message(message) for message in messages)

    def estimate_prompt_payload(self, payload: PromptPayload) -> int:
        return (
            self.estimate_text(payload.system)
            + self.estimate_value(payload.messages)
            + self.estimate_value(payload.tools)
            + self.estimate_value(payload.metadata)
            + 16
        )


class ContextManager:
    def __init__(
        self,
        *,
        root_dir: Path,
        provider: ChatProvider,
        config: ContextConfig | None = None,
    ) -> None:
        self.root_dir = root_dir.resolve()
        self.provider = provider
        self.config = config or ContextConfig()
        self.estimator = TokenEstimator()
        self._states: dict[str, ContextSessionState] = {}

    def state_for(self, session: ChatSession) -> ContextSessionState:
        state = self._states.setdefault(session.session_id, ContextSessionState())
        if state.session_context is None:
            spill_dir = self._session_cache_dir(session) / "tool-results"
            spill_dir.mkdir(parents=True, exist_ok=True)
            state.session_context = SessionContext(session_id=session.session_id, spill_dir=str(spill_dir))
        return state

    def record_usage(self, session: ChatSession, usage: ProviderUsage) -> None:
        state = self.state_for(session)
        state.last_usage = usage
        anchor = usage_anchor(usage)
        if anchor > 0:
            state.anchored_input_tokens = anchor
            state.anchored_message_count = len(session.messages)

    def estimate_session_tokens(self, session: ChatSession) -> int:
        state = self.state_for(session)
        current = self.estimator.estimate_messages(session.messages)
        if state.anchored_input_tokens is None:
            return current
        anchored_messages = session.messages[: state.anchored_message_count]
        anchored_estimate = self.estimator.estimate_messages(anchored_messages)
        current_delta = max(0, current - anchored_estimate)
        return max(current, state.anchored_input_tokens + current_delta)

    def estimate_request_tokens(
        self,
        session: ChatSession,
        tool_definitions: list[dict[str, Any]],
        *,
        mode: str = "normal",
        model_request_index: int = 0,
    ) -> int:
        payload = assemble_api_payload(
            session_messages=session.snapshot(),
            tools=tool_definitions,
            root_dir=self.root_dir,
            mode=mode,
            model_request_index=model_request_index,
        )
        current = self.estimator.estimate_prompt_payload(payload)
        state = self.state_for(session)
        if state.anchored_input_tokens is None:
            return current
        anchored_messages = session.messages[: state.anchored_message_count]
        anchored_estimate = self.estimator.estimate_messages(anchored_messages)
        current_session = self.estimator.estimate_messages(session.messages)
        current_delta = max(0, current_session - anchored_estimate)
        return max(current, state.anchored_input_tokens + current_delta)

    def process_tool_result(
        self,
        session: ChatSession,
        tool_call: ToolCall,
        result: dict[str, Any],
        tool_id: str | None = None,
    ) -> dict[str, Any]:
        processed = self._spill_result_if_needed(session, tool_call.name, result, tool_id)
        self._remember_read_snapshot(session, tool_call, processed)
        return processed

    def prepare_before_request(
        self,
        session: ChatSession,
        tool_definitions: list[dict[str, Any]],
        *,
        mode: str = "normal",
        model_request_index: int = 0,
        emit_started: bool = True,
    ) -> ContextOperationResult:
        self._spill_existing_tool_results(session)
        self._sanitize_session_messages(session)
        before_tokens = self.estimate_request_tokens(
            session,
            tool_definitions,
            mode=mode,
            model_request_index=model_request_index,
        )
        threshold = self._auto_compact_threshold()
        if before_tokens < threshold:
            return ContextOperationResult()
        state = self.state_for(session)
        if state.auto_compact_disabled:
            return ContextOperationResult(
                events=[
                    ContextCompressionSkipped(
                        kind="auto",
                        reason="auto_compact_disabled_after_repeated_failures",
                        before_tokens=before_tokens,
                    )
                ],
                skipped=True,
            )
        return self.compact(
            session,
            tool_definitions=tool_definitions,
            kind="auto",
            mode=mode,
            model_request_index=model_request_index,
            emit_started=emit_started,
        )

    def compact(
        self,
        session: ChatSession,
        *,
        tool_definitions: list[dict[str, Any]] | None = None,
        kind: CompactKind = "manual",
        mode: str = "normal",
        model_request_index: int = 0,
        focus: str = "",
        bypass_breaker: bool = False,
        emit_started: bool = True,
    ) -> ContextOperationResult:
        self._spill_existing_tool_results(session)
        tool_definitions = tool_definitions or []
        before_tokens = self.estimate_request_tokens(
            session,
            tool_definitions,
            mode=mode,
            model_request_index=model_request_index,
        )
        state = self.state_for(session)
        old_messages, recent_messages = self._split_messages_for_summary(session.messages)
        if not old_messages:
            return ContextOperationResult(
                events=[ContextCompressionSkipped(kind=kind, reason="nothing_to_compact", before_tokens=before_tokens)],
                skipped=True,
            )

        events: list[ContextEvent] = [ContextCompressionStarted(kind=kind, before_tokens=before_tokens)] if emit_started else []
        if kind == "auto" and state.auto_compact_disabled and not bypass_breaker:
            summary = self._deterministic_summary(old_messages, reason="LLM summary disabled after repeated failures.")
            events.append(
                ContextCompressionFallbackUsed(
                    kind=kind,
                    reason="LLM summary disabled after repeated failures.",
                    quality="local",
                    consecutive_failures=state.summary_failures,
                )
            )
            return self._apply_compacted_summary(
                session,
                summary,
                recent_messages,
                tool_definitions,
                kind,
                before_tokens,
                events,
                mode=mode,
                model_request_index=model_request_index,
                reset_summary_failures=False,
                summary_quality="local",
            )

        try:
            summary, summary_events = self._request_summary(old_messages, recent_messages, kind=kind, focus=focus)
            events.extend(summary_events)
            if not summary.strip():
                raise ContextError("Summary provider returned empty content.")
            return self._apply_compacted_summary(
                session,
                summary,
                recent_messages,
                tool_definitions,
                kind,
                before_tokens,
                events,
                mode=mode,
                model_request_index=model_request_index,
                reset_summary_failures=True,
                summary_quality="llm",
            )
        except Exception as exc:
            if kind == "auto":
                state.summary_failures += 1
                if state.summary_failures >= self.config.max_summary_failures:
                    state.auto_compact_disabled = True
            events.append(
                ContextCompressionFallbackUsed(
                    kind=kind,
                    reason=str(exc),
                    quality="llm_failed",
                    consecutive_failures=state.summary_failures if kind == "auto" else 0,
                )
            )
            summary = self._deterministic_summary(
                old_messages,
                reason=f"LLM summary failed, so MewCode used a local fallback summary: {exc}",
            )
            return self._apply_compacted_summary(
                session,
                summary,
                recent_messages,
                tool_definitions,
                kind,
                before_tokens,
                events,
                mode=mode,
                model_request_index=model_request_index,
                reset_summary_failures=False,
                summary_quality="llm_failed",
            )

    def _apply_compacted_summary(
        self,
        session: ChatSession,
        summary: str,
        recent_messages: list[Message],
        tool_definitions: list[dict[str, Any]],
        kind: CompactKind,
        before_tokens: int,
        events: list[ContextEvent],
        *,
        mode: str,
        model_request_index: int,
        reset_summary_failures: bool,
        summary_quality: str = "llm",
    ) -> ContextOperationResult:
        target_tokens = self._target_tokens_after_compact(kind)
        recovery_message = self._recovery_message(session, summary, tool_definitions, target_tokens)
        session.messages = [recovery_message, *[message.copy() for message in recent_messages]]
        self._sanitize_session_messages(session)
        state = self.state_for(session)
        state.anchored_input_tokens = None
        state.anchored_message_count = 0
        state.last_usage = None
        self._fit_compacted_session_to_target(
            session,
            tool_definitions,
            target_tokens,
            mode=mode,
            model_request_index=model_request_index,
        )
        self._sanitize_session_messages(session)
        after_tokens = self.estimate_request_tokens(
            session,
            tool_definitions,
            mode=mode,
            model_request_index=model_request_index,
        )
        state.last_compaction_before_tokens = before_tokens
        state.last_compaction_after_tokens = after_tokens
        if reset_summary_failures:
            state.summary_failures = 0
            state.auto_compact_disabled = False
        events.append(
            ContextCompressionFinished(
                kind=kind,
                before_tokens=before_tokens,
                after_tokens=after_tokens,
                reduced_tokens=max(0, before_tokens - after_tokens),
                summary_tokens=self.estimator.estimate_text(summary),
                summary_quality=summary_quality,
            )
        )
        return ContextOperationResult(events=events, compacted=True)

    def _is_compact_recovery_message(self, message: Message) -> bool:
        if message.get("role") != "user":
            return False
        content = str(message.get("content") or "")
        return "Previous context was compacted" in content and "## Compacted Summary" in content

    def _target_tokens_after_compact(self, kind: CompactKind) -> int:
        margin = self.config.manual_margin_tokens if kind == "manual" else self.config.auto_margin_tokens
        return max(1, self.config.context_window_tokens - margin)

    def _auto_compact_threshold(self) -> int:
        if self.config.context_window_tokens > SUMMARY_RESERVE + self.config.auto_margin_tokens:
            return max(1, self.config.context_window_tokens - SUMMARY_RESERVE - self.config.auto_margin_tokens)
        return max(1, self.config.context_window_tokens - self.config.auto_margin_tokens)

    def prepare_start_event(
        self,
        session: ChatSession,
        tool_definitions: list[dict[str, Any]],
        *,
        mode: str = "normal",
        model_request_index: int = 0,
    ) -> ContextCompressionStarted | None:
        self._spill_existing_tool_results(session)
        before_tokens = self.estimate_request_tokens(
            session,
            tool_definitions,
            mode=mode,
            model_request_index=model_request_index,
        )
        threshold = self._auto_compact_threshold()
        if before_tokens < threshold:
            return None
        if self.state_for(session).auto_compact_disabled:
            return None
        old_messages, _ = self._split_messages_for_summary(session.messages)
        if not old_messages:
            return None
        return ContextCompressionStarted(kind="auto", before_tokens=before_tokens)

    def compact_start_event(
        self,
        session: ChatSession,
        tool_definitions: list[dict[str, Any]] | None = None,
        kind: CompactKind = "manual",
        *,
        mode: str = "normal",
        model_request_index: int = 0,
    ) -> ContextCompressionStarted | None:
        self._spill_existing_tool_results(session)
        before_tokens = self.estimate_request_tokens(
            session,
            tool_definitions or [],
            mode=mode,
            model_request_index=model_request_index,
        )
        old_messages, _ = self._split_messages_for_summary(session.messages)
        if not old_messages:
            return None
        return ContextCompressionStarted(kind=kind, before_tokens=before_tokens)

    def report_stats(
        self,
        session: ChatSession,
        tool_definitions: list[dict[str, Any]] | None = None,
        *,
        mode: str = "normal",
        model_request_index: int = 0,
    ) -> ContextStatsReported:
        tool_definitions = tool_definitions or []
        payload = assemble_api_payload(
            session_messages=session.snapshot(),
            tools=tool_definitions,
            root_dir=self.root_dir,
            mode=mode,
            model_request_index=model_request_index,
        )
        state = self.state_for(session)
        old_messages, recent_messages = self._split_messages_for_summary(session.messages)
        return ContextStatsReported(
            estimated_tokens=self.estimate_request_tokens(
                session,
                tool_definitions,
                mode=mode,
                model_request_index=model_request_index,
            ),
            system_prompt_tokens=self.estimator.estimate_text(payload.system),
            tools_tokens=self.estimator.estimate_value(payload.tools),
            user_history_tokens=sum(
                self.estimator.estimate_message(message)
                for message in session.messages
                if message.get("role") == "user" and not self._is_compact_recovery_message(message)
            ),
            assistant_history_tokens=sum(
                self.estimator.estimate_message(message)
                for message in session.messages
                if message.get("role") == "assistant"
            ),
            tool_result_tokens=sum(
                self.estimator.estimate_message(message)
                for message in session.messages
                if message.get("role") == "tool"
            ),
            compact_summary_tokens=sum(
                self.estimator.estimate_message(message)
                for message in session.messages
                if self._is_compact_recovery_message(message)
            ),
            recent_raw_tokens=self.estimator.estimate_messages(recent_messages),
            auto_threshold_tokens=self._auto_compact_threshold(),
            context_window_tokens=self.config.context_window_tokens,
            auto_compact_disabled=state.auto_compact_disabled,
            last_compaction_before_tokens=state.last_compaction_before_tokens,
            last_compaction_after_tokens=state.last_compaction_after_tokens,
        )

    def _deterministic_summary(self, messages: list[Message], reason: str) -> str:
        user_messages: list[str] = []
        tool_lines: list[str] = []
        assistant_count = 0
        for message in messages:
            role = str(message.get("role") or "")
            if role == "user":
                user_messages.append(self._message_preview(message, limit=360))
            elif role == "assistant":
                assistant_count += 1
            elif role == "tool":
                tool_name = str(message.get("tool_name") or "tool")
                result = message.get("tool_result")
                metadata = result.get("metadata") if isinstance(result, dict) else {}
                path = metadata.get("stored_path") if isinstance(metadata, dict) else ""
                suffix = f"; stored at {path}" if path else ""
                tool_lines.append(f"- {tool_name}: {self._message_preview(message, limit=240)}{suffix}")

        user_text = "\n".join(f"- {item}" for item in user_messages[-20:]) or "- No user messages in compacted range."
        tool_text = "\n".join(tool_lines[-30:]) or "- No tool results in compacted range."
        return (
            "## 1. Current Task Goal\n"
            "Continue the current user task using the compacted conversation context.\n\n"
            "## 2. User Messages Verbatim\n"
            f"{user_text}\n\n"
            "## 3. User Requirements And Preferences\n"
            "- Preserve explicit user requirements from recent uncompressed messages.\n"
            "- Re-read files or stored tool result paths when exact details are needed.\n\n"
            "## 4. Completed Actions And Conclusions\n"
            f"- MewCode compacted {len(messages)} older message(s).\n"
            f"- Assistant messages compacted: {assistant_count}.\n"
            f"- Fallback reason: {reason}\n\n"
            "## 5. Important Files Read Written Or Edited\n"
            "- See tool result entries below. Re-read files for exact content.\n\n"
            "## 6. Important Commands And Tool Results\n"
            f"{tool_text}\n\n"
            "## 7. Current Code And Project Understanding\n"
            "- Exact source code is not preserved in this local fallback summary.\n\n"
            "## 8. Remaining Work And Next Steps\n"
            "- Continue from the recent uncompressed messages.\n"
            "- Use read/search tools before making claims about exact source content.\n\n"
            "## 9. Constraints Permissions Stored Result Paths And Mistakes To Avoid\n"
            "- Do not infer exact code from this summary.\n"
            "- Stored tool result paths, if listed, can be read again for full details."
        )

    def _message_preview(self, message: Message, limit: int = 320) -> str:
        try:
            text = json.dumps(message, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            text = str(message)
        text = " ".join(text.split())
        if len(text) <= limit:
            return text
        return text[: limit - 3] + "..."

    def is_context_length_error(self, exc: Exception) -> bool:
        if exc.__class__.__name__ == "PromptTooLongError":
            return True
        text = str(exc).lower()
        patterns = [
            "prompt_too_long",
            "context length",
            "maximum context",
            "context window",
            "too many tokens",
            "input is too long",
        ]
        return any(pattern in text for pattern in patterns)

    def _split_messages_for_summary(self, messages: list[Message]) -> tuple[list[Message], list[Message]]:
        if len(messages) <= self.config.min_recent_messages:
            return [], [message.copy() for message in messages]

        recent: list[Message] = []
        recent_tokens = 0
        recent_token_target = self._effective_recent_token_target()
        for message in reversed(messages):
            recent.append(message.copy())
            recent_tokens += self.estimator.estimate_message(message)
            if len(recent) >= self.config.min_recent_messages and recent_tokens >= recent_token_target:
                break
        recent.reverse()
        old_count = max(0, len(messages) - len(recent))
        if old_count == 0 and len(messages) > self.config.min_recent_messages:
            recent = [message.copy() for message in messages[-self.config.min_recent_messages :]]
            old_count = len(messages) - len(recent)
        return [message.copy() for message in messages[:old_count]], recent

    def _effective_recent_token_target(self) -> int:
        usable_window = max(1, self.config.context_window_tokens - self.config.auto_margin_tokens)
        return max(1, min(self.config.recent_token_target, usable_window // 2))

    def _request_summary(
        self,
        old_messages: list[Message],
        recent_messages: list[Message],
        *,
        kind: CompactKind,
        focus: str = "",
    ) -> tuple[str, list[ContextEvent]]:
        chunks = self._summary_chunks(old_messages)
        events: list[ContextEvent] = []
        if len(chunks) <= 1:
            prompt = self._summary_prompt(old_messages, recent_messages, focus=focus, purpose="final")
            summary = self._complete_summary_prompt(prompt)
            return summary, events

        chunk_summaries: list[str] = []
        for index, chunk in enumerate(chunks, start=1):
            input_tokens = self.estimator.estimate_messages(chunk)
            events.append(
                ContextChunkSummaryStarted(
                    kind=kind,
                    chunk_index=index,
                    chunk_count=len(chunks),
                    input_tokens=input_tokens,
                )
            )
            prompt = self._summary_prompt(chunk, None, focus=focus, purpose="chunk")
            chunk_summary = self._complete_summary_prompt(prompt)
            chunk_summaries.append(chunk_summary)
            events.append(
                ContextChunkSummaryFinished(
                    kind=kind,
                    chunk_index=index,
                    chunk_count=len(chunks),
                    output_tokens=self.estimator.estimate_text(chunk_summary),
                )
            )

        merge_messages = [
            {"role": "user", "content": f"Chunk summary {index}:\n{summary}"}
            for index, summary in enumerate(chunk_summaries, start=1)
        ]
        merge_prompt = self._summary_prompt(merge_messages, recent_messages, focus=focus, purpose="final")
        return self._complete_summary_prompt(merge_prompt), events

    def _complete_summary_prompt(self, prompt: str) -> str:
        payload = PromptPayload(
            system=SUMMARY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            tools=[],
            cache_policy=CachePolicy(cache_system=False, cache_tools=False),
            metadata={"context_compaction": True},
        )
        response = self.provider.complete_chat(payload, tools=[])
        return extract_final_summary(response.text or "")

    def _summary_prompt(
        self,
        old_messages: list[Message],
        recent_messages: list[Message] | None,
        *,
        focus: str = "",
        purpose: str = "final",
    ) -> str:
        clean_focus = focus.strip()[: self.config.compact_focus_max_chars]
        return build_summary_prompt(old_messages, recent_messages, focus=clean_focus, purpose=purpose)

    def _summary_chunks(self, messages: list[Message]) -> list[list[Message]]:
        groups = self._group_messages_by_user_turn(messages)
        chunks: list[list[Message]] = []
        current: list[Message] = []
        current_tokens = 0
        for group in groups:
            group_tokens = self.estimator.estimate_messages(group)
            if current and current_tokens + group_tokens > self.config.summary_chunk_target_tokens:
                chunks.append(current)
                current = []
                current_tokens = 0
            if group_tokens > self.config.summary_chunk_max_tokens and not current:
                chunks.extend(self._split_large_group(group))
                continue
            current.extend(message.copy() for message in group)
            current_tokens += group_tokens
        if current:
            chunks.append(current)
        return chunks or [[]]

    def _group_messages_by_user_turn(self, messages: list[Message]) -> list[list[Message]]:
        groups: list[list[Message]] = []
        current: list[Message] = []
        for message in messages:
            if message.get("role") == "user" and current:
                groups.append(current)
                current = [message.copy()]
            else:
                current.append(message.copy())
        if current:
            groups.append(current)
        return groups

    def _split_large_group(self, group: list[Message]) -> list[list[Message]]:
        chunks: list[list[Message]] = []
        current: list[Message] = []
        current_tokens = 0
        for message in group:
            message_tokens = self.estimator.estimate_message(message)
            if current and current_tokens + message_tokens > self.config.summary_chunk_max_tokens:
                chunks.append(current)
                current = []
                current_tokens = 0
            current.append(message.copy())
            current_tokens += message_tokens
        if current:
            chunks.append(current)
        return chunks

    def _recovery_message(
        self,
        session: ChatSession,
        summary: str,
        tool_definitions: list[dict[str, Any]],
        target_tokens: int,
    ) -> Message:
        summary_budget = max(80, min(4000, target_tokens // 3))
        snapshot_budget = max(40, min(1000, target_tokens // 8))
        tools_budget = max(40, min(800, target_tokens // 10))
        summary = self._trim_text_to_tokens(summary.strip(), summary_budget)
        snapshots = self._trim_text_to_tokens(self._read_snapshot_text(session), snapshot_budget)
        tools = self._trim_text_to_tokens(self._tool_overview(tool_definitions), tools_budget)
        boundary = (
            "The context above is a compacted summary, not exact source text. "
            f"{BOUNDARY_NOTICE}"
        )
        content = (
            "<system-reminder>\n"
            "Previous context was compacted to stay within the model context window.\n\n"
            "## Compacted Summary\n"
            f"{summary.strip()}\n\n"
            "## Recently Read File Snapshots\n"
            f"{snapshots}\n\n"
            "## Current Available Tools\n"
            f"{tools}\n\n"
            "## Boundary Reminder\n"
            f"{boundary}\n"
            "</system-reminder>"
        )
        return {"role": "user", "content": content}

    def _fit_compacted_session_to_target(
        self,
        session: ChatSession,
        tool_definitions: list[dict[str, Any]],
        target_tokens: int,
        *,
        mode: str,
        model_request_index: int,
    ) -> None:
        if self.estimate_request_tokens(session, tool_definitions, mode=mode, model_request_index=model_request_index) <= target_tokens:
            return
        for message in session.messages:
            result = message.get("tool_result")
            if not isinstance(result, dict):
                continue
            metadata = result.get("metadata") or {}
            if not isinstance(metadata, dict) or not metadata.get("stored_on_disk"):
                continue
            message["tool_result"] = self._stored_result_placeholder(result)
            if self.estimate_request_tokens(session, tool_definitions, mode=mode, model_request_index=model_request_index) <= target_tokens:
                return
        if self.estimate_request_tokens(session, tool_definitions, mode=mode, model_request_index=model_request_index) <= target_tokens:
            return
        recovery = session.messages[0] if session.messages else None
        if recovery is not None and recovery.get("role") == "user":
            content = str(recovery.get("content") or "")
            recovery["content"] = self._minimal_recovery_content(content, max(80, target_tokens // 3))
        if self.estimate_request_tokens(session, tool_definitions, mode=mode, model_request_index=model_request_index) <= target_tokens:
            return
        for index in range(1, max(1, len(session.messages) - 1)):
            message = session.messages[index]
            session.messages[index] = self._compacted_recent_placeholder(message)
            if self.estimate_request_tokens(session, tool_definitions, mode=mode, model_request_index=model_request_index) <= target_tokens:
                return
        if self.estimate_request_tokens(session, tool_definitions, mode=mode, model_request_index=model_request_index) <= target_tokens:
            return
        for index in range(1, len(session.messages)):
            message = session.messages[index]
            if message.get("role") == "user":
                content = str(message.get("content") or "")
                message["content"] = self._trim_text_to_tokens(content, 120)
            if self.estimate_request_tokens(session, tool_definitions, mode=mode, model_request_index=model_request_index) <= target_tokens:
                return

    def _sanitize_session_messages(self, session: ChatSession) -> None:
        session.messages = self._sanitize_tool_message_pairs(session.messages)

    def _sanitize_tool_message_pairs(self, messages: list[Message]) -> list[Message]:
        sanitized: list[Message] = []
        index = 0
        while index < len(messages):
            message = messages[index]
            if message.get("role") == "assistant" and self._assistant_tool_calls(message):
                index = self._append_sanitized_tool_exchange(messages, index, sanitized)
                continue
            if message.get("role") == "tool":
                index += 1
                continue
            sanitized.append(message.copy())
            index += 1
        return sanitized

    def _append_sanitized_tool_exchange(
        self,
        messages: list[Message],
        assistant_index: int,
        sanitized: list[Message],
    ) -> int:
        assistant = messages[assistant_index]
        calls = self._assistant_tool_calls(assistant)
        tool_index = assistant_index + 1
        tool_messages: list[Message] = []
        while tool_index < len(messages) and messages[tool_index].get("role") == "tool":
            tool_messages.append(messages[tool_index])
            tool_index += 1

        result_ids = {self._tool_result_id(message) for message in tool_messages}
        matched_calls = [call for call in calls if self._tool_call_payload_id(call) in result_ids]
        if not matched_calls:
            sanitized.append(
                {
                    "role": "assistant",
                    "content": (
                        "[Assistant tool calls omitted after context compaction. "
                        "Re-read files or rerun tools if exact results are needed.]"
                    ),
                }
            )
            return tool_index

        sanitized_assistant = assistant.copy()
        if "tool_calls" in sanitized_assistant:
            sanitized_assistant["tool_calls"] = [call.copy() for call in matched_calls]
            sanitized_assistant.pop("tool_input", None)
            sanitized_assistant.pop("tool_name", None)
            sanitized_assistant.pop("tool_id", None)
        sanitized.append(sanitized_assistant)

        matched_ids = {self._tool_call_payload_id(call) for call in matched_calls}
        for tool_message in tool_messages:
            if self._tool_result_id(tool_message) in matched_ids:
                sanitized.append(tool_message.copy())
        return tool_index

    def _assistant_tool_calls(self, message: Message) -> list[dict[str, Any]]:
        raw_calls = message.get("tool_calls")
        if isinstance(raw_calls, list):
            return [call for call in raw_calls if isinstance(call, dict)]
        if message.get("tool_input") is not None:
            return [
                {
                    "id": str(message.get("tool_id") or message.get("tool_name") or "tool"),
                    "name": str(message.get("tool_name") or "tool"),
                    "arguments": dict(message.get("tool_input") or {}),
                }
            ]
        return []

    def _tool_call_payload_id(self, call: dict[str, Any]) -> str:
        return str(call.get("id") or call.get("name") or "tool")

    def _tool_result_id(self, message: Message) -> str:
        return str(message.get("tool_id") or message.get("tool_name") or "tool")

    def _stored_result_placeholder(self, result: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(result.get("metadata") or {})
        stored_path = str(metadata.get("stored_path") or "")
        if stored_path:
            content = (
                f"[Full tool result stored on disk at {stored_path}. "
                "Preview omitted after context compaction. Read this file again if exact details are needed.]"
            )
        else:
            content = "[Tool result preview omitted after context compaction. Re-run or re-read if exact details are needed.]"
        payload = {
            "ok": bool(result.get("ok")),
            "content": content,
            "metadata": metadata,
        }
        if result.get("error") is not None:
            payload["error"] = str(result.get("error"))
        return payload

    def _compacted_recent_placeholder(self, message: Message) -> Message:
        role = message.get("role")
        if role == "tool":
            result = message.get("tool_result")
            if isinstance(result, dict):
                return {
                    "role": "tool",
                    "tool_name": str(message.get("tool_name") or "tool"),
                    "tool_result": self._stored_result_placeholder(result),
                    **({"tool_id": str(message["tool_id"])} if message.get("tool_id") else {}),
                }
            return {
                "role": "tool",
                "tool_name": str(message.get("tool_name") or "tool"),
                "tool_result": {"ok": True, "content": "[Tool result omitted after context compaction.]", "metadata": {}},
                **({"tool_id": str(message["tool_id"])} if message.get("tool_id") else {}),
            }
        if role == "assistant":
            return {
                "role": "assistant",
                "content": (
                    "[Assistant message omitted after context compaction. Use the compacted summary and re-read files "
                    "or stored tool result paths for exact details.]"
                ),
            }
        if role == "user":
            content = str(message.get("content") or "")
            return {"role": "user", "content": self._trim_text_to_tokens(content, 180)}
        return {"role": "user", "content": "[Message omitted after context compaction.]"}

    def _minimal_recovery_content(self, content: str, max_tokens: int) -> str:
        trimmed = self._trim_text_to_tokens(content, max_tokens)
        return (
            "<system-reminder>\n"
            "Previous context was compacted aggressively to stay within the model context window.\n"
            "The summary below is incomplete; re-read files or stored tool result paths before relying on exact details.\n\n"
            f"{trimmed}\n"
            "</system-reminder>"
        )

    def _trim_text_to_tokens(self, text: str, max_tokens: int) -> str:
        if self.estimator.estimate_text(text) <= max_tokens:
            return text
        suffix = "\n...[truncated to fit context budget]"
        suffix_tokens = self.estimator.estimate_text(suffix)
        budget = max(1, max_tokens - suffix_tokens)
        low = 0
        high = len(text)
        while low < high:
            mid = (low + high + 1) // 2
            if self.estimator.estimate_text(text[:mid]) <= budget:
                low = mid
            else:
                high = mid - 1
        return text[:low].rstrip() + suffix

    def _read_snapshot_text(self, session: ChatSession) -> str:
        snapshots = list(self.state_for(session).read_snapshots.values())[-10:]
        if not snapshots:
            return "- None recorded."
        lines: list[str] = []
        for snapshot in snapshots:
            detail = snapshot.preview.replace("\n", " ").strip()
            if len(detail) > 240:
                detail = detail[:237] + "..."
            suffix = f" stored at {snapshot.stored_path}" if snapshot.stored_path else ""
            lines.append(f"- {snapshot.path}: {detail}{suffix}")
        return "\n".join(lines)

    def _tool_overview(self, tool_definitions: list[dict[str, Any]]) -> str:
        if not tool_definitions:
            return "- No tools in current request."
        names = [str(tool.get("name") or "") for tool in tool_definitions if tool.get("name")]
        names = names[:80]
        return "\n".join(f"- {name}" for name in names) if names else "- No tools in current request."

    def _remember_read_snapshot(self, session: ChatSession, tool_call: ToolCall, result: dict[str, Any]) -> None:
        if tool_call.name != "ReadFile" or not result.get("ok"):
            return
        raw_path = tool_call.arguments.get("path") or (result.get("metadata") or {}).get("path")
        if not raw_path:
            return
        content = self._read_snapshot_content(str(raw_path), fallback=str(result.get("content") or ""))
        metadata = result.get("metadata") or {}
        stored_path = str(metadata.get("stored_path") or "")
        self.state_for(session).read_snapshots[str(raw_path)] = ReadSnapshot(
            path=str(raw_path),
            preview=content[: self.config.preview_chars],
            stored_path=stored_path,
        )

    def _read_snapshot_content(self, raw_path: str, fallback: str) -> str:
        path = Path(raw_path)
        if not path.is_absolute():
            path = self.root_dir / path
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return fallback

    def _spill_existing_tool_results(self, session: ChatSession) -> None:
        tool_messages = [message for message in session.messages if message.get("role") == "tool"]
        aggregate_bytes = sum(result_size(message.get("tool_result"))[0] for message in tool_messages)
        aggregate_tokens = sum(result_size(message.get("tool_result"), self.estimator)[1] for message in tool_messages)
        force_aggregate = (
            aggregate_bytes > self.config.aggregate_result_byte_threshold
            or aggregate_tokens > self.config.aggregate_result_token_threshold
        )
        ordered = sorted(
            tool_messages,
            key=lambda message: result_size(message.get("tool_result"), self.estimator)[0],
            reverse=True,
        )
        for message in ordered:
            result = message.get("tool_result")
            if not isinstance(result, dict):
                continue
            if not force_aggregate and not self._should_spill_result(result):
                continue
            tool_name = str(message.get("tool_name") or "tool")
            tool_id = str(message.get("tool_id") or "")
            message["tool_result"] = self._store_result(session, tool_name, result, tool_id or None)
            aggregate_bytes = sum(result_size(candidate.get("tool_result"))[0] for candidate in tool_messages)
            aggregate_tokens = sum(result_size(candidate.get("tool_result"), self.estimator)[1] for candidate in tool_messages)
            force_aggregate = (
                aggregate_bytes > self.config.aggregate_result_byte_threshold
                or aggregate_tokens > self.config.aggregate_result_token_threshold
            )
            if not force_aggregate:
                break

    def _spill_result_if_needed(
        self,
        session: ChatSession,
        tool_name: str,
        result: dict[str, Any],
        tool_id: str | None,
    ) -> dict[str, Any]:
        if not self._should_spill_result(result):
            return result
        return self._store_result(session, tool_name, result, tool_id)

    def _should_spill_result(self, result: dict[str, Any]) -> bool:
        if (result.get("metadata") or {}).get("stored_on_disk"):
            return False
        size_bytes, size_tokens = result_size(result, self.estimator)
        return (
            size_bytes > self.config.single_result_byte_threshold
            or size_tokens > self.config.single_result_token_threshold
        )

    def _store_result(
        self,
        session: ChatSession,
        tool_name: str,
        result: dict[str, Any],
        tool_id: str | None,
    ) -> dict[str, Any]:
        state = self.state_for(session)
        assert state.session_context is not None
        return spill_tool_result(
            root_dir=self.root_dir,
            session=state.session_context,
            replacement_state=state.replacement_state,
            tool_name=tool_name,
            result=result,
            tool_id=tool_id,
            preview_head_bytes=self.config.tool_preview_head_chars,
            preview_tail_bytes=self.config.tool_preview_tail_chars,
        )

    def _session_cache_dir(self, session: ChatSession) -> Path:
        path = (self.root_dir / self.config.cache_dir / session.session_id).resolve()
        path.relative_to(self.root_dir)
        return path


class ContextError(Exception):
    pass


SUMMARY_SYSTEM_PROMPT = (
    "You are MewCode's context compaction worker. You summarize conversation history only. "
    "You must not call tools. Preserve user requirements accurately and do not invent source details."
)


def extract_final_summary(text: str) -> str:
    return extract_summary(text)


def result_size(result: Any, estimator: TokenEstimator | None = None) -> tuple[int, int]:
    size_bytes, _ = compact_result_size(result)
    token_estimator = estimator or TokenEstimator()
    try:
        text = json.dumps(result, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        text = str(result)
    return size_bytes, token_estimator.estimate_text(text)


def safe_filename(value: str) -> str:
    return compact_safe_filename(value)
