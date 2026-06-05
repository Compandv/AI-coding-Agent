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
