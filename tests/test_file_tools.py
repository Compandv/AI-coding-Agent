from pathlib import Path

import pytest

from mewcode.tools.base import ToolError
from mewcode.tools.context import ToolContext
from mewcode.tools.file_tools import EditFileTool, ReadFileTool, WriteFileTool


def context(tmp_path):
    return ToolContext(root_dir=tmp_path)


def test_read_file_returns_content(tmp_path):
    path = tmp_path / "note.txt"
    path.write_text("hello", encoding="utf-8")

    result = ReadFileTool().execute({"path": "note.txt"}, context(tmp_path))

    assert result.ok is True
    assert result.content == "hello"
    assert result.metadata["content_chars"] == 5
    assert result.metadata["content_bytes"] == 5
    assert result.metadata["line_count"] == 1
    assert result.metadata["truncated"] is False


def test_read_file_reports_truncation_metadata(tmp_path):
    path = tmp_path / "large.txt"
    path.write_text("abcdef", encoding="utf-8")

    result = ReadFileTool().execute({"path": "large.txt"}, ToolContext(root_dir=tmp_path, max_output_chars=3))

    assert result.content == "abc\n...[truncated]"
    assert result.metadata["content_chars"] == 6
    assert result.metadata["content_bytes"] == 6
    assert result.metadata["truncated"] is True


def test_read_file_returns_line_range(tmp_path):
    path = tmp_path / "note.txt"
    path.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")

    result = ReadFileTool().execute(
        {"path": "note.txt", "start_line": 2, "end_line": 3},
        context(tmp_path),
    )

    assert result.ok is True
    assert result.content == "two\nthree"
    assert result.metadata["content_chars"] == 19
    assert result.metadata["line_count"] == 4
    assert result.metadata["range_requested"] is True
    assert result.metadata["start_line"] == 2
    assert result.metadata["end_line"] == 3
    assert result.metadata["returned_line_count"] == 2
    assert result.metadata["returned_chars"] == 9


def test_read_file_line_range_defaults_to_file_start_or_end(tmp_path):
    path = tmp_path / "note.txt"
    path.write_text("one\ntwo\nthree\nfour", encoding="utf-8")

    first_half = ReadFileTool().execute({"path": "note.txt", "end_line": 2}, context(tmp_path))
    tail = ReadFileTool().execute({"path": "note.txt", "start_line": 3}, context(tmp_path))

    assert first_half.content == "one\ntwo"
    assert first_half.metadata["start_line"] == 1
    assert first_half.metadata["end_line"] == 2
    assert tail.content == "three\nfour"
    assert tail.metadata["start_line"] == 3
    assert tail.metadata["end_line"] == 4


def test_read_file_treats_empty_optional_line_values_as_unset(tmp_path):
    path = tmp_path / "note.txt"
    path.write_text("one\ntwo\nthree", encoding="utf-8")

    result = ReadFileTool().execute(
        {"path": "note.txt", "start_line": "", "end_line": "  "},
        context(tmp_path),
    )

    assert result.ok is True
    assert result.content == "one\ntwo\nthree"
    assert result.metadata["range_requested"] is True
    assert result.metadata["start_line"] == 1
    assert result.metadata["end_line"] == 3


def test_read_file_rejects_invalid_line_range(tmp_path):
    path = tmp_path / "note.txt"
    path.write_text("one\ntwo\nthree", encoding="utf-8")

    with pytest.raises(ToolError, match="end_line"):
        ReadFileTool().execute({"path": "note.txt", "start_line": 3, "end_line": 2}, context(tmp_path))
    with pytest.raises(ToolError, match="start_line"):
        ReadFileTool().execute({"path": "note.txt", "start_line": 0}, context(tmp_path))


def test_read_file_line_range_truncates_returned_content(tmp_path):
    path = tmp_path / "note.txt"
    path.write_text("one\ntwo\nthree", encoding="utf-8")

    result = ReadFileTool().execute(
        {"path": "note.txt", "start_line": 2},
        ToolContext(root_dir=tmp_path, max_output_chars=5),
    )

    assert result.content == "two\nt\n...[truncated]"
    assert result.metadata["content_chars"] == 13
    assert result.metadata["returned_chars"] == 9
    assert result.metadata["truncated"] is True


def test_write_file_creates_file(tmp_path):
    result = WriteFileTool().execute({"path": "dir/note.txt", "content": "hello"}, context(tmp_path))

    assert result.ok is True
    assert (tmp_path / "dir" / "note.txt").read_text(encoding="utf-8") == "hello"


def test_edit_file_replaces_unique_match(tmp_path):
    path = tmp_path / "note.txt"
    path.write_text("hello world", encoding="utf-8")

    result = EditFileTool().execute(
        {"path": "note.txt", "old_string": "world", "new_string": "agent"},
        context(tmp_path),
    )

    assert result.ok is True
    assert path.read_text(encoding="utf-8") == "hello agent"


def test_edit_file_rejects_missing_match(tmp_path):
    path = tmp_path / "note.txt"
    path.write_text("hello world", encoding="utf-8")

    with pytest.raises(ToolError):
        EditFileTool().execute(
            {"path": "note.txt", "old_string": "missing", "new_string": "agent"},
            context(tmp_path),
        )


def test_edit_file_rejects_multiple_matches(tmp_path):
    path = tmp_path / "note.txt"
    path.write_text("world world", encoding="utf-8")

    with pytest.raises(ToolError):
        EditFileTool().execute(
            {"path": "note.txt", "old_string": "world", "new_string": "agent"},
            context(tmp_path),
        )
