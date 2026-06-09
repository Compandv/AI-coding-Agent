from pathlib import Path

from mewcode.compact.layer1 import build_preview, spill_single, spill_tool_result
from mewcode.compact.state import ContentReplacementState, new_session_context


def test_spill_single_is_idempotent(tmp_path):
    session = new_session_context(tmp_path)

    path = spill_single(session, "read_1", "hello")
    first_mtime = path.stat().st_mtime_ns
    second_path = spill_single(session, "read_1", "changed")

    assert second_path == path
    assert path.stat().st_mtime_ns == first_mtime
    assert path.read_text(encoding="utf-8") == "hello"


def test_build_preview_contains_head_tail_and_precision_warning():
    preview = build_preview(
        60000,
        "line 1\nline 2",
        "tail 1\ntail 2",
        ".mewcode/sessions/s/tool-results/read_1",
    )

    assert "original size: 60000 bytes" in preview
    assert "[head preview]" in preview
    assert "[tail preview]" in preview
    assert "line 1" in preview
    assert "tail 2" in preview
    assert ".mewcode/sessions/s/tool-results/read_1" in preview
    assert "Read that path again" in preview
    assert "Do not infer full details from this preview" in preview


def test_spill_tool_result_uses_tool_call_id_as_filename(tmp_path):
    session = new_session_context(tmp_path)
    state = ContentReplacementState()
    result = {"ok": True, "content": "x" * 60000, "metadata": {}}

    processed = spill_tool_result(
        root_dir=tmp_path,
        session=session,
        replacement_state=state,
        tool_name="ReadFile",
        result=result,
        tool_id="read_1",
    )

    stored_path = tmp_path / processed["metadata"]["stored_path"]
    assert stored_path == Path(session.spill_dir) / "read_1"
    assert stored_path.read_text(encoding="utf-8") == "x" * 60000
    assert processed["metadata"]["stored_on_disk"] is True
    assert "Full tool result stored on disk" in processed["content"]
    assert "[tail preview]" in processed["content"]


def test_spill_tool_result_reuses_frozen_preview(tmp_path):
    session = new_session_context(tmp_path)
    state = ContentReplacementState()
    first = spill_tool_result(
        root_dir=tmp_path,
        session=session,
        replacement_state=state,
        tool_name="ReadFile",
        result={"ok": True, "content": "x" * 60000, "metadata": {}},
        tool_id="read_1",
    )
    second = spill_tool_result(
        root_dir=tmp_path,
        session=session,
        replacement_state=state,
        tool_name="ReadFile",
        result={"ok": True, "content": "y" * 60000, "metadata": {}},
        tool_id="read_1",
    )

    assert second["content"] == first["content"]
