from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

from mewcode.session import ChatSession, Message


@dataclass(frozen=True)
class SessionInfo:
    session_id: str
    path: Path
    title: str
    message_count: int
    updated_at: datetime | None = None


@dataclass(frozen=True)
class SessionRestoreResult:
    session: ChatSession
    warnings: list[str]
    skipped_bad_lines: int = 0
    truncated: bool = False
    elapsed_notice: str = ""


class SessionStore:
    def __init__(self, project_root: Path, retention_days: int = 30) -> None:
        self.project_root = project_root.resolve()
        self.retention_days = retention_days
        self.sessions_dir = self.project_root / ".mewcode" / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def attach(self, session: ChatSession) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        session.set_observer(lambda event_type, payload: self.record(session.session_id, event_type, payload))

    def record(self, session_id: str, event_type: str, payload: dict[str, Any]) -> None:
        path = self.path_for(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "type": event_type,
            "session_id": session_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            **payload,
        }
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            handle.write("\n")

    def path_for(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.jsonl"

    def list_sessions(self) -> list[SessionInfo]:
        infos = [self._info_from_path(path) for path in self.sessions_dir.glob("*.jsonl")]
        fallback_time = datetime.min.replace(tzinfo=timezone.utc)
        return sorted((info for info in infos if info is not None), key=lambda item: item.updated_at or fallback_time, reverse=True)

    def rename(self, session_id: str, title: str) -> bool:
        path = self.path_for(session_id)
        if not path.exists():
            return False
        self.record(session_id, "session_title", {"title": title})
        return True

    def restore(self, session_id: str) -> SessionRestoreResult:
        path = self.path_for(session_id)
        warnings: list[str] = []
        messages: list[Message] = []
        skipped_bad_lines = 0
        if not path.exists():
            return SessionRestoreResult(ChatSession(session_id=session_id), [f"Session not found: {session_id}"])

        last_time: datetime | None = None
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                skipped_bad_lines += 1
                warnings.append(f"Skipped bad JSONL line {line_number}.")
                continue
            last_time = self._parse_time(record.get("created_at")) or last_time
            event_type = record.get("type")
            if event_type == "append_message":
                message = record.get("message")
                if isinstance(message, dict):
                    messages.append(message)  # type: ignore[arg-type]
            elif event_type == "replace_messages":
                raw_messages = record.get("messages")
                if isinstance(raw_messages, list):
                    messages = [message for message in raw_messages if isinstance(message, dict)]  # type: ignore[list-item]

        messages, truncated = self._repair_tool_pairs(messages)
        if truncated:
            warnings.append("Truncated session at incomplete tool call/result chain.")
        elapsed_notice = self._elapsed_notice(last_time)
        session = ChatSession(session_id=session_id, messages=messages)
        return SessionRestoreResult(
            session=session,
            warnings=warnings,
            skipped_bad_lines=skipped_bad_lines,
            truncated=truncated,
            elapsed_notice=elapsed_notice,
        )

    def delete(self, session_id: str) -> bool:
        path = self.path_for(session_id)
        if not path.exists():
            return False
        path.unlink()
        cache_dir = self.sessions_dir / session_id
        if cache_dir.exists() and cache_dir.is_dir():
            self._remove_dir(cache_dir)
        return True

    def cleanup_expired(self) -> list[str]:
        if self.retention_days <= 0:
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        removed: list[str] = []
        for info in self.list_sessions():
            if info.updated_at is None or info.updated_at >= cutoff:
                continue
            if self.delete(info.session_id):
                removed.append(info.session_id)
        return removed

    def _info_from_path(self, path: Path) -> SessionInfo | None:
        session_id = path.stem
        messages: list[Message] = []
        updated_at: datetime | None = None
        title_override = ""
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            updated_at = self._parse_time(record.get("created_at")) or updated_at
            if record.get("type") == "append_message" and isinstance(record.get("message"), dict):
                messages.append(record["message"])
            elif record.get("type") == "replace_messages" and isinstance(record.get("messages"), list):
                messages = [message for message in record["messages"] if isinstance(message, dict)]  # type: ignore[list-item]
            elif record.get("type") == "session_title":
                title_override = str(record.get("title") or "").strip()
        title = title_override or self._title_from_messages(messages)
        return SessionInfo(session_id=session_id, path=path, title=title, message_count=len(messages), updated_at=updated_at)

    def _title_from_messages(self, messages: list[Message]) -> str:
        for message in messages:
            if message.get("role") == "user" and message.get("content"):
                text = " ".join(str(message["content"]).split())
                return text[:60] or "(untitled)"
        return "(untitled)"

    def _repair_tool_pairs(self, messages: list[Message]) -> tuple[list[Message], bool]:
        expected: list[str] = []
        safe_messages: list[Message] = []
        for message in messages:
            if message.get("role") == "assistant" and isinstance(message.get("tool_calls"), list):
                calls = [call for call in message.get("tool_calls", []) if isinstance(call, dict)]
                ids = [str(call.get("id") or "") for call in calls]
                expected.extend(ids)
                safe_messages.append(message)
                continue
            if message.get("role") == "tool":
                tool_id = str(message.get("tool_id") or "")
                if not expected or tool_id not in expected:
                    return safe_messages, True
                expected.remove(tool_id)
                safe_messages.append(message)
                continue
            if expected:
                return safe_messages, True
            safe_messages.append(message)
        if expected:
            return safe_messages[:-1] if safe_messages else [], True
        return safe_messages, False

    def _elapsed_notice(self, last_time: datetime | None) -> str:
        if last_time is None:
            return ""
        elapsed = datetime.now(timezone.utc) - last_time
        if elapsed < timedelta(hours=24):
            return ""
        days = max(1, elapsed.days)
        return f"Restored session after about {days} day(s). Re-check stale assumptions before acting."

    def _parse_time(self, value: Any) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _remove_dir(self, path: Path) -> None:
        for child in path.iterdir():
            if child.is_dir():
                self._remove_dir(child)
            else:
                child.unlink()
        path.rmdir()
