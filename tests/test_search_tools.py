from mewcode.tools.context import ToolContext
from mewcode.tools.search_tools import GlobTool, GrepTool


def context(tmp_path):
    return ToolContext(root_dir=tmp_path)


def test_glob_finds_matching_files(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("print('a')", encoding="utf-8")
    (tmp_path / "src" / "b.txt").write_text("text", encoding="utf-8")

    result = GlobTool().execute({"pattern": "src/*.py"}, context(tmp_path))

    assert result.ok is True
    assert result.metadata["paths"] == ["src\\a.py"] or result.metadata["paths"] == ["src/a.py"]


def test_grep_finds_matching_lines(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("hello\nagent\n", encoding="utf-8")

    result = GrepTool().execute({"query": "agent"}, context(tmp_path))

    assert result.ok is True
    assert "agent" in result.content
    assert result.metadata["count"] == 1
