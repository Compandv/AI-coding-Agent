from mewcode.compact.state import AutoCompactTrackingState, ContentReplacementState, RecoveryState, new_session_context


def test_new_session_context_creates_session_directory(tmp_path):
    first = new_session_context(tmp_path)
    second = new_session_context(tmp_path)

    assert first.session_id != second.session_id
    assert first.session_id.count("-") == 1
    assert (tmp_path / ".mewcode" / "sessions" / first.session_id / "tool-results").exists()


def test_content_replacement_state_freezes_replaced_preview():
    state = ContentReplacementState()

    first = state.decide_once("call_1", "original", lambda: ("replaced", "preview"))
    second = state.decide_once("call_1", "changed original", lambda: ("replaced", "different"))

    assert first == "preview"
    assert second == "preview"


def test_content_replacement_state_skip_does_not_mark_seen():
    state = ContentReplacementState()

    first = state.decide_once("call_1", "original", lambda: ("skip", ""))
    second = state.decide_once("call_1", "original", lambda: ("replaced", "preview"))

    assert first == "original"
    assert second == "preview"


def test_auto_compact_tracking_trips_and_resets():
    state = AutoCompactTrackingState()

    state.record_failure()
    state.record_failure()
    assert state.tripped() is False

    state.record_failure()
    assert state.tripped() is True

    state.record_success()
    assert state.tripped() is False


def test_recovery_state_returns_snapshot_copy_sorted_by_latest(tmp_path):
    state = RecoveryState()
    state.record_file(tmp_path / "a.txt", "a")
    state.record_file(tmp_path / "b.txt", "b")

    snapshot = state.snapshot()
    snapshot.clear()

    next_snapshot = state.snapshot()
    assert len(next_snapshot) == 2
    assert next_snapshot[0].path.endswith("b.txt")
