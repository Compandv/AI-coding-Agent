from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .const import PREVIEW_HEAD_BYTES, PREVIEW_HEAD_LINES, PREVIEW_TAIL_BYTES, PREVIEW_TAIL_LINES
from .state import ContentReplacementState, SessionContext


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return cleaned.strip("-") or "tool"


def _stable_tool_id(tool_name: str, content: str, tool_id: str | None) -> str:
    if tool_id:
        return safe_filename(tool_id)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
    return f"{safe_filename(tool_name)}-{digest}"


def _result_text(result: dict[str, Any]) -> str:
    value = result.get("content")
    if value is None:
        value = result.get("error")
    if value is None:
        try:
            return json.dumps(result, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            return str(result)
    return str(value)


def utf8_len(text: str) -> int:
    return len(text.encode("utf-8"))


def _truncate_utf8(text: str, limit: int) -> str:
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text
    return data[:limit].decode("utf-8", errors="ignore")


def _tail_truncate_utf8(text: str, limit: int) -> str:
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text
    return data[-limit:].decode("utf-8", errors="ignore")


def head_preview(
    content: str,
    byte_limit: int = PREVIEW_HEAD_BYTES,
    line_limit: int = PREVIEW_HEAD_LINES,
) -> str:
    lines = content.splitlines(keepends=True)[:line_limit]
    head = "".join(lines)
    return _truncate_utf8(head, byte_limit)


def _legacy_head_only_preview(original_bytes: int, head: str, spill_path: str) -> str:
    return (
        f"[content offloaded] original size: {original_bytes} bytes\n"
        f"[saved to] {spill_path}\n"
        "[head preview]\n"
        f"{head.rstrip()}\n\n"
        f"[Full tool result stored on disk at {spill_path}. "
        "完整内容已保存到上述路径；如需查看请用文件读取工具读取该路径，不要凭头部预览猜测全文。]"
    )


def spill_single(session: SessionContext, tool_use_id: str, content: str) -> Path:
    path = Path(session.spill_dir) / safe_filename(tool_use_id)
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8"))
    return path


def tail_preview(
    content: str,
    byte_limit: int = PREVIEW_TAIL_BYTES,
    line_limit: int = PREVIEW_TAIL_LINES,
) -> str:
    lines = content.splitlines(keepends=True)[-line_limit:]
    tail = "".join(lines)
    return _tail_truncate_utf8(tail, byte_limit)


def build_preview(original_bytes: int, head: str, tail: str, spill_path: str) -> str:
    return (
        f"[content offloaded] original size: {original_bytes} bytes\n"
        f"[saved to] {spill_path}\n"
        "[head preview]\n"
        f"{head.rstrip()}\n\n"
        "[middle omitted; full result is stored on disk]\n\n"
        "[tail preview]\n"
        f"{tail.rstrip()}\n\n"
        f"[Full tool result stored on disk at {spill_path}. "
        "Read that path again when exact content, complete logs, or precise code is needed. "
        "Do not infer full details from this preview.]"
    )


def result_size(result: Any) -> tuple[int, int]:
    try:
        text = json.dumps(result, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        text = str(result)
    size_bytes = len(text.encode("utf-8"))
    return size_bytes, max(1, size_bytes // 4)


def spill_tool_result(
    *,
    root_dir: Path,
    session: SessionContext,
    replacement_state: ContentReplacementState,
    tool_name: str,
    result: dict[str, Any],
    tool_id: str | None,
    preview_head_bytes: int = PREVIEW_HEAD_BYTES,
    preview_tail_bytes: int = PREVIEW_TAIL_BYTES,
) -> dict[str, Any]:
    metadata = dict(result.get("metadata") or {})
    if metadata.get("stored_on_disk"):
        return result

    original = _result_text(result)
    use_id = _stable_tool_id(tool_name, original, tool_id)
    original_bytes = utf8_len(original)
    stored_path = Path(session.spill_dir) / safe_filename(use_id)

    def decide() -> tuple[str, str]:
        try:
            spill_single(session, use_id, original)
        except OSError:
            return "skip", ""
        return "replaced", build_preview(
            original_bytes,
            head_preview(original, byte_limit=preview_head_bytes),
            tail_preview(original, byte_limit=preview_tail_bytes),
            _display_path(root_dir, stored_path),
        )

    preview = replacement_state.decide_once(use_id, original, decide)
    if preview == original and replacement_state.replacement_for(use_id) is None:
        return result

    metadata.update(
        {
            "stored_on_disk": True,
            "stored_path": _display_path(root_dir, stored_path),
            "session_id": session.session_id,
            "original_result_chars": len(original),
            "original_result_bytes": original_bytes,
            "original_result_estimated_tokens": max(1, original_bytes // 4),
            "spilled_freed_chars": max(0, len(original) - len(preview)),
            "tool_name": tool_name,
            "tool_id": use_id,
        }
    )
    payload: dict[str, Any] = {
        "ok": bool(result.get("ok")),
        "content": preview,
        "metadata": metadata,
    }
    if result.get("error") is not None:
        payload["error"] = str(result.get("error"))
    return payload


def _display_path(root_dir: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root_dir.resolve()).as_posix()
    except ValueError:
        return str(path)
