from pathlib import Path

from mewcode.context import (
    ContextChunkSummaryFinished,
    ContextChunkSummaryStarted,
    ContextCompressionFallbackUsed,
    ContextCompressionFailed,
    ContextCompressionFinished,
    ContextCompressionSkipped,
    ContextConfig,
    ContextStatsReported,
    ContextEmergencyRetry,
    ContextManager,
    TokenEstimator,
    extract_final_summary,
)
from mewcode.providers.base import ChatResponse, ProviderUsage, ToolCall
from mewcode.session import ChatSession


class FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete_chat(self, messages, tools=None):
        self.calls.append({"messages": messages, "tools": tools})
        return self.responses.pop(0)


def test_token_estimator_is_stable_and_uses_tool_results():
    estimator = TokenEstimator()
    message = {"role": "tool", "tool_name": "ReadFile", "tool_result": {"ok": True, "content": "abcd" * 20}}

    first = estimator.estimate_message(message)
    second = estimator.estimate_message(message)

    assert first == second
    assert first > estimator.estimate_text("abcd")


def test_session_has_stable_unique_id():
    first = ChatSession()
    second = ChatSession()

    assert first.session_id
    assert second.session_id
    assert first.session_id != second.session_id


def test_large_tool_result_is_stored_in_session_specific_directory(tmp_path):
    manager = ContextManager(root_dir=tmp_path, provider=FakeProvider([]))
    session = ChatSession()
    result = {"ok": True, "content": "x" * 51000, "metadata": {}}

    processed = manager.process_tool_result(
        session,
        ToolCall(name="ReadFile", arguments={"path": "large.txt"}),
        result,
        "read_1",
    )

    metadata = processed["metadata"]
    stored_path = tmp_path / metadata["stored_path"]
    assert metadata["stored_on_disk"] is True
    assert metadata["session_id"] == session.session_id
    assert session.session_id in metadata["stored_path"]
    assert stored_path.exists()
    assert "Full tool result stored on disk" in processed["content"]
    assert "[head preview]" in processed["content"]
    assert "[tail preview]" in processed["content"]


def test_large_tool_result_preview_keeps_tail_error_context(tmp_path):
    manager = ContextManager(
        root_dir=tmp_path,
        provider=FakeProvider([]),
        config=ContextConfig(
            single_result_byte_threshold=1000,
            tool_preview_head_chars=64,
            tool_preview_tail_chars=128,
        ),
    )
    session = ChatSession()
    content = "head line\n" + ("middle\n" * 2000) + "FINAL ERROR: command failed\n"

    processed = manager.process_tool_result(
        session,
        ToolCall(name="Bash", arguments={"command": "pytest"}),
        {"ok": False, "content": content, "error": "failed", "metadata": {}},
        "bash_1",
    )

    assert "[head preview]" in processed["content"]
    assert "[tail preview]" in processed["content"]
    assert "head line" in processed["content"]
    assert "FINAL ERROR: command failed" in processed["content"]


def test_context_cache_isolated_between_sessions(tmp_path):
    manager = ContextManager(root_dir=tmp_path, provider=FakeProvider([]))
    first = ChatSession()
    second = ChatSession()

    first_result = manager.process_tool_result(
        first,
        ToolCall(name="ReadFile", arguments={"path": "a.txt"}),
        {"ok": True, "content": "a" * 51000, "metadata": {}},
        "a",
    )
    second_result = manager.process_tool_result(
        second,
        ToolCall(name="ReadFile", arguments={"path": "b.txt"}),
        {"ok": True, "content": "b" * 51000, "metadata": {}},
        "b",
    )

    assert first_result["metadata"]["stored_path"] != second_result["metadata"]["stored_path"]
    assert first.session_id in first_result["metadata"]["stored_path"]
    assert second.session_id in second_result["metadata"]["stored_path"]


def test_manual_compact_replaces_old_messages_and_preserves_recent_tail(tmp_path):
    summary = """<analysis>scratch</analysis>
<final_summary>
## 1. Current Task Goal
Keep working.
</final_summary>"""
    manager = ContextManager(
        root_dir=tmp_path,
        provider=FakeProvider([ChatResponse(text=summary)]),
        config=ContextConfig(recent_token_target=10, min_recent_messages=2),
    )
    session = ChatSession()
    for index in range(8):
        session.add_user_message(f"user {index}")
        session.add_assistant_message(f"assistant {index}")

    result = manager.compact(
        session,
        tool_definitions=[{"name": "ReadFile"}, {"name": "context7__resolve"}],
        kind="manual",
        bypass_breaker=True,
    )

    assert result.compacted is True
    assert any(isinstance(event, ContextCompressionFinished) for event in result.events)
    assert session.messages[0]["role"] == "user"
    assert "Compacted Summary" in session.messages[0]["content"]
    assert "Current Available Tools" in session.messages[0]["content"]
    assert "ReadFile" in session.messages[0]["content"]
    assert "context7__resolve" in session.messages[0]["content"]
    assert "assistant 7" in session.messages[-1]["content"]
    assert "<analysis>" not in session.messages[0]["content"]


def test_manual_compact_uses_chunk_summaries_before_final_merge(tmp_path):
    provider = FakeProvider([ChatResponse(text="<summary>chunk summary</summary>") for _ in range(20)])
    manager = ContextManager(
        root_dir=tmp_path,
        provider=provider,
        config=ContextConfig(
            recent_token_target=1,
            min_recent_messages=2,
            summary_chunk_target_tokens=80,
            summary_chunk_max_tokens=160,
        ),
    )
    session = ChatSession()
    for index in range(10):
        session.add_user_message(f"user hard requirement {index} " + "x" * 140)
        session.add_assistant_message(f"assistant action {index} " + "y" * 140)

    result = manager.compact(session, tool_definitions=[], kind="manual", bypass_breaker=True)

    started = [event for event in result.events if isinstance(event, ContextChunkSummaryStarted)]
    finished = [event for event in result.events if isinstance(event, ContextChunkSummaryFinished)]
    assert result.compacted is True
    assert len(started) >= 2
    assert len(finished) == len(started)
    assert len(provider.calls) == len(started) + 1
    assert "Chunk summary" in provider.calls[-1]["messages"].messages[0]["content"]


def test_manual_compact_focus_is_injected_into_summary_prompt(tmp_path):
    provider = FakeProvider([ChatResponse(text="<summary>focused summary</summary>")])
    manager = ContextManager(
        root_dir=tmp_path,
        provider=provider,
        config=ContextConfig(recent_token_target=10, min_recent_messages=2),
    )
    session = ChatSession()
    for index in range(8):
        session.add_user_message(f"user {index}")
        session.add_assistant_message(f"assistant {index}")

    manager.compact(
        session,
        tool_definitions=[],
        kind="manual",
        focus="重点保留第八章 context.py 实现细节",
        bypass_breaker=True,
    )

    prompt = provider.calls[0]["messages"].messages[0]["content"]
    assert "[user supplied compact focus]" in prompt
    assert "重点保留第八章 context.py 实现细节" in prompt


def test_auto_compact_failure_breaker_is_session_isolated(tmp_path):
    class FailingProvider:
        def complete_chat(self, messages, tools=None):
            raise RuntimeError("summary failed")

    manager = ContextManager(
        root_dir=tmp_path,
        provider=FailingProvider(),
        config=ContextConfig(context_window_tokens=50, auto_margin_tokens=10, max_summary_failures=3),
    )
    first = ChatSession()
    second = ChatSession()
    for session in (first, second):
        for index in range(10):
            session.add_user_message("x" * 100)

    for _ in range(3):
        manager.prepare_before_request(first, [])

    assert manager.state_for(first).auto_compact_disabled is True
    assert manager.state_for(second).auto_compact_disabled is False


def test_compact_falls_back_to_local_summary_when_llm_summary_fails(tmp_path):
    class FailingProvider:
        def complete_chat(self, messages, tools=None):
            raise RuntimeError("summary failed")

    manager = ContextManager(
        root_dir=tmp_path,
        provider=FailingProvider(),
        config=ContextConfig(recent_token_target=10, min_recent_messages=2),
    )
    session = ChatSession()
    for index in range(8):
        session.add_user_message(f"user {index}")
        session.add_assistant_message(f"assistant {index}")

    result = manager.compact(session, tool_definitions=[{"name": "ReadFile"}], kind="manual", bypass_breaker=True)

    assert result.compacted is True
    failed_events = [event for event in result.events if isinstance(event, ContextCompressionFailed)]
    fallback_events = [event for event in result.events if isinstance(event, ContextCompressionFallbackUsed)]
    finished_events = [event for event in result.events if isinstance(event, ContextCompressionFinished)]
    assert failed_events == []
    assert fallback_events
    assert finished_events
    assert fallback_events[0].quality == "llm_failed"
    assert fallback_events[0].consecutive_failures == 0
    assert finished_events[-1].summary_quality == "llm_failed"
    assert "Fallback reason" in session.messages[0]["content"]
    assert "LLM summary failed" in session.messages[0]["content"]
    assert "assistant 7" in session.messages[-1]["content"]


def test_context_stats_report_breaks_down_token_sources(tmp_path):
    manager = ContextManager(root_dir=tmp_path, provider=FakeProvider([]))
    session = ChatSession()
    session.add_user_message("hello")
    session.add_assistant_message("hi")
    session.add_tool_calls([{"id": "read_1", "name": "ReadFile", "arguments": {"path": "a.txt"}}])
    session.add_tool_result("ReadFile", {"ok": True, "content": "file text", "metadata": {}}, tool_id="read_1")
    manager.state_for(session).last_compaction_before_tokens = 1000
    manager.state_for(session).last_compaction_after_tokens = 500

    stats = manager.report_stats(session, [{"name": "ReadFile"}])

    assert isinstance(stats, ContextStatsReported)
    assert stats.estimated_tokens > 0
    assert stats.system_prompt_tokens > 0
    assert stats.tools_tokens > 0
    assert stats.tool_result_tokens > 0
    assert stats.last_compaction_before_tokens == 1000
    assert stats.last_compaction_after_tokens == 500


def test_auto_compact_fits_small_window_by_omitting_stored_tool_previews(tmp_path):
    class FailingProvider:
        def complete_chat(self, messages, tools=None):
            raise RuntimeError("summary timed out")

    manager = ContextManager(
        root_dir=tmp_path,
        provider=FailingProvider(),
        config=ContextConfig(context_window_tokens=5000, auto_margin_tokens=1000),
    )
    session = ChatSession()
    for index in range(16):
        session.add_user_message(f"user requirement {index} " + "x" * 240)
        session.add_assistant_message(f"assistant answer {index} " + "y" * 240)
    session.add_tool_calls(
        [
            {"id": f"read_{index}", "name": "ReadFile", "arguments": {"path": f"file-{index}.py"}}
            for index in range(4)
        ]
    )
    for index in range(4):
        session.add_tool_result(
            "ReadFile",
            {
                "ok": True,
                "content": "preview " + ("z" * 9000),
                "metadata": {
                    "stored_on_disk": True,
                    "stored_path": f".mewcode/context/session/tool-results/read-{index}.json",
                },
            },
            tool_id=f"read_{index}",
        )
    session.add_user_message("continue after the reads")

    result = manager.prepare_before_request(session, [{"name": "ReadFile"}])

    finished = [event for event in result.events if isinstance(event, ContextCompressionFinished)]
    assert finished
    assert finished[-1].after_tokens <= 4000
    assert manager.estimate_session_tokens(session) <= 4000
    assert _has_no_orphan_tool_results(session.messages)


def test_auto_compact_budget_includes_system_messages_and_tool_definitions(tmp_path):
    class FailingProvider:
        def complete_chat(self, messages, tools=None):
            raise RuntimeError("summary timed out")

    manager = ContextManager(
        root_dir=tmp_path,
        provider=FailingProvider(),
        config=ContextConfig(context_window_tokens=15000, auto_margin_tokens=3000),
    )
    session = ChatSession()
    for index in range(30):
        session.add_user_message(f"user {index} " + "x" * 900)
        session.add_assistant_message(f"assistant {index} " + "y" * 900)
    tool_definitions = [
        {
            "name": f"ExternalTool{index}",
            "description": "large external tool description " + ("z" * 1200),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "q" * 600},
                },
            },
        }
        for index in range(8)
    ]

    result = manager.prepare_before_request(session, tool_definitions)

    finished = [event for event in result.events if isinstance(event, ContextCompressionFinished)]
    assert finished
    assert finished[-1].after_tokens <= 12000
    assert finished[-1].after_tokens == manager.estimate_request_tokens(session, tool_definitions)


def test_auto_compact_small_window_does_not_trigger_below_legacy_margin_threshold(tmp_path):
    class FailingProvider:
        def complete_chat(self, messages, tools=None):
            raise AssertionError("summary should not be requested below the small-window threshold")

    manager = ContextManager(
        root_dir=tmp_path,
        provider=FailingProvider(),
        config=ContextConfig(context_window_tokens=15000, auto_margin_tokens=3000, min_recent_messages=2),
    )
    session = ChatSession()
    for index in range(3):
        session.add_user_message(f"user {index} " + "x" * 1000)

    before = manager.estimate_request_tokens(session, [])
    result = manager.prepare_before_request(session, [])

    assert 1 < before < 12000
    assert result.events == []
    assert result.compacted is False


def test_compact_removes_orphan_tool_results_after_recent_tail_trimming(tmp_path):
    class FailingProvider:
        def complete_chat(self, messages, tools=None):
            raise RuntimeError("summary timed out")

    manager = ContextManager(
        root_dir=tmp_path,
        provider=FailingProvider(),
        config=ContextConfig(
            context_window_tokens=1200,
            manual_margin_tokens=100,
            recent_token_target=1,
            min_recent_messages=2,
        ),
    )
    session = ChatSession()
    for index in range(8):
        session.add_user_message(f"old user {index} " + "x" * 160)
        session.add_assistant_message(f"old assistant {index} " + "y" * 160)
    session.add_tool_calls(
        [
            {
                "id": "call_read",
                "name": "ReadFile",
                "arguments": {"path": "large.py"},
            }
        ]
    )
    session.add_tool_result(
        "ReadFile",
        {
            "ok": True,
            "content": "preview " + ("z" * 20000),
            "metadata": {
                "stored_on_disk": True,
                "stored_path": ".mewcode/sessions/s/tool-results/call_read",
            },
        },
        tool_id="call_read",
    )

    result = manager.compact(session, tool_definitions=[{"name": "ReadFile"}], kind="manual", bypass_breaker=True)

    assert result.compacted is True
    assert _has_no_orphan_tool_results(session.messages)


def test_prepare_before_request_drops_preexisting_orphan_tool_result(tmp_path):
    manager = ContextManager(root_dir=tmp_path, provider=FakeProvider([]))
    session = ChatSession()
    session.add_user_message("hello")
    session.add_tool_result("ReadFile", {"ok": True, "content": "orphan", "metadata": {}}, tool_id="missing_call")

    result = manager.prepare_before_request(session, [])

    assert result.events == []
    assert [message["role"] for message in session.messages] == ["user"]


def _has_no_orphan_tool_results(messages):
    pending_ids: set[str] = set()
    for message in messages:
        if message.get("role") == "assistant":
            pending_ids = {
                str(call.get("id") or call.get("name") or "tool")
                for call in message.get("tool_calls") or []
                if isinstance(call, dict)
            }
            continue
        if message.get("role") == "tool":
            tool_id = str(message.get("tool_id") or message.get("tool_name") or "tool")
            if tool_id not in pending_ids:
                return False
            continue
        pending_ids = set()
    return True


def test_compact_clears_provider_usage_anchor_after_replacing_history(tmp_path):
    class FailingProvider:
        def complete_chat(self, messages, tools=None):
            raise RuntimeError("summary timed out")

    manager = ContextManager(
        root_dir=tmp_path,
        provider=FailingProvider(),
        config=ContextConfig(context_window_tokens=5000, auto_margin_tokens=1000),
    )
    session = ChatSession()
    for index in range(12):
        session.add_user_message(f"user {index} " + "x" * 300)
        session.add_assistant_message(f"assistant {index} " + "y" * 300)
    manager.record_usage(session, ProviderUsage(input_tokens=8500))
    session.add_tool_result(
        "ReadFile",
        {
            "ok": True,
            "content": "preview " + ("z" * 12000),
            "metadata": {
                "stored_on_disk": True,
                "stored_path": ".mewcode/context/session/tool-results/read.json",
            },
        },
        tool_id="read_1",
    )

    result = manager.prepare_before_request(session, [{"name": "ReadFile"}])

    finished = [event for event in result.events if isinstance(event, ContextCompressionFinished)]
    assert finished
    assert finished[-1].after_tokens <= 4000
    state = manager.state_for(session)
    assert state.anchored_input_tokens is None
    assert state.anchored_message_count == 0


def test_manual_compact_can_bypass_auto_breaker(tmp_path):
    manager = ContextManager(
        root_dir=tmp_path,
        provider=FakeProvider([ChatResponse(text="<final_summary>Recovered.</final_summary>")]),
        config=ContextConfig(context_window_tokens=50, auto_margin_tokens=10, max_summary_failures=3, min_recent_messages=2),
    )
    session = ChatSession()
    for index in range(8):
        session.add_user_message("x" * 80)
    state = manager.state_for(session)
    state.auto_compact_disabled = True
    state.summary_failures = 3

    result = manager.compact(session, tool_definitions=[], kind="manual", bypass_breaker=True)

    assert result.compacted is True
    assert manager.state_for(session).auto_compact_disabled is False


def test_usage_anchor_updates_estimate(tmp_path):
    manager = ContextManager(root_dir=tmp_path, provider=FakeProvider([]))
    session = ChatSession()
    session.add_user_message("small")

    before = manager.estimate_session_tokens(session)
    manager.record_usage(session, ProviderUsage(input_tokens=4096))
    session.add_assistant_message("more")

    assert manager.estimate_session_tokens(session) > before
    assert manager.estimate_session_tokens(session) >= 4096


def test_extract_final_summary_discards_analysis():
    text = "<analysis>scratch</analysis><final_summary>final only</final_summary>"

    assert extract_final_summary(text) == "final only"


def test_nothing_to_compact_is_observable(tmp_path):
    manager = ContextManager(root_dir=tmp_path, provider=FakeProvider([]))
    session = ChatSession()
    session.add_user_message("hello")

    result = manager.compact(session, kind="manual", bypass_breaker=True)

    assert result.skipped is True
    assert isinstance(result.events[0], ContextCompressionSkipped)
