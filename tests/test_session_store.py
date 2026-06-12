import json
from datetime import datetime, timedelta, timezone

from mewcode.memory import SessionStore
from mewcode.session import ChatSession


def test_session_store_appends_jsonl_and_restores_messages(tmp_path):
    store = SessionStore(tmp_path)
    session = ChatSession(session_id="20260610-010203-abcd")
    store.attach(session)

    session.add_user_message("hello")
    session.add_assistant_message("hi")

    path = store.path_for(session.session_id)
    assert path.exists()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["type"] == "append_message"

    restored = store.restore(session.session_id)
    assert restored.session.snapshot() == session.snapshot()


def test_session_store_skips_bad_lines_and_truncates_orphan_tool_result(tmp_path):
    store = SessionStore(tmp_path)
    session_id = "20260610-010203-bad1"
    path = store.path_for(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                json.dumps({"type": "append_message", "message": {"role": "user", "content": "hi"}}),
                "{bad json",
                json.dumps(
                    {
                        "type": "append_message",
                        "message": {"role": "tool", "tool_id": "missing", "tool_name": "ReadFile", "tool_result": {}},
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    restored = store.restore(session_id)

    assert restored.skipped_bad_lines == 1
    assert restored.truncated is True
    assert restored.session.snapshot() == [{"role": "user", "content": "hi"}]


def test_session_store_reports_elapsed_notice_for_old_session(tmp_path):
    store = SessionStore(tmp_path)
    session_id = "20260501-010203-old1"
    old_time = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    store.path_for(session_id).write_text(
        json.dumps(
            {
                "type": "append_message",
                "created_at": old_time,
                "message": {"role": "user", "content": "old"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    restored = store.restore(session_id)

    assert "Restored session after about" in restored.elapsed_notice


def test_session_store_rename_overrides_list_title(tmp_path):
    store = SessionStore(tmp_path)
    session = ChatSession(session_id="20260610-010203-name")
    store.attach(session)
    session.add_user_message("original title")

    assert store.rename(session.session_id, "custom title") is True

    info = store.list_sessions()[0]
    assert info.title == "custom title"


def test_session_store_lists_sessions_with_missing_and_aware_timestamps(tmp_path):
    store = SessionStore(tmp_path)
    missing_time_id = "20260610-010203-none"
    aware_time_id = "20260610-010204-aware"
    store.path_for(missing_time_id).write_text(
        json.dumps({"type": "append_message", "message": {"role": "user", "content": "missing time"}}) + "\n",
        encoding="utf-8",
    )
    store.path_for(aware_time_id).write_text(
        json.dumps(
            {
                "type": "append_message",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "message": {"role": "user", "content": "aware time"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    infos = store.list_sessions()

    assert {info.session_id for info in infos} == {missing_time_id, aware_time_id}
