from datetime import datetime, timedelta

from mewcode.compact.const import RECOVERY_FILE_LIMIT
from mewcode.compact.recovery import BOUNDARY_NOTICE, build_recovery_attachment
from mewcode.compact.state import FileReadRecord


def test_recovery_attachment_limits_files_and_lists_tools():
    now = datetime.now()
    records = [
        FileReadRecord(path=f"file_{index}.py", content=f"content {index}", timestamp=now - timedelta(seconds=index))
        for index in range(RECOVERY_FILE_LIMIT + 2)
    ]
    tools = [{"name": "ReadFile", "description": "Read files", "input_schema": {"type": "object"}}]

    text = build_recovery_attachment(records, tools)

    assert "最近读过的文件" in text
    assert "当前可用工具" in text
    assert "ReadFile" in text
    assert "file_0.py" in text
    assert "file_5.py" not in text
    assert BOUNDARY_NOTICE in text


def test_recovery_attachment_truncates_long_file_content():
    record = FileReadRecord(path="large.py", content="x" * 30000, timestamp=datetime.now())

    text = build_recovery_attachment([record], [])

    assert "(content truncated)" in text
