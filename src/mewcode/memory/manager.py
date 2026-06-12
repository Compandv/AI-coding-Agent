from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mewcode.memory.instructions import InstructionBundle, InstructionLoader
from mewcode.memory.memory_store import MemoryStore
from mewcode.memory.session_store import SessionStore
from mewcode.prompts import system_reminder_message
from mewcode.session import ChatSession, Message


@dataclass(frozen=True)
class MemoryRuntimeConfig:
    enabled: bool = True
    auto_extract: bool = True
    session_retention_days: int = 30
    include_max_depth: int = 5
    index_max_lines: int = 200
    index_max_bytes: int = 25_000


class MemoryContextManager:
    def __init__(
        self,
        project_root: Path,
        config: MemoryRuntimeConfig | None = None,
        user_home: Path | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.config = config or MemoryRuntimeConfig()
        self.user_home = (user_home or Path.home()).resolve()
        self.instructions = InstructionLoader(
            self.project_root,
            user_home=self.user_home,
            max_include_depth=self.config.include_max_depth,
        )
        self.sessions = SessionStore(self.project_root, retention_days=self.config.session_retention_days)
        self.memories = MemoryStore(
            self.project_root,
            user_home=self.user_home,
            index_max_lines=self.config.index_max_lines,
            index_max_bytes=self.config.index_max_bytes,
        )
        self.auto_memory_enabled = self.config.auto_extract
        self.last_instruction_bundle = InstructionBundle([])
        self.last_status: dict[str, int] = {"instructions": 0, "memories": 0}
        self._restore_notice = ""

    def attach_session(self, session: ChatSession) -> None:
        if self.config.enabled:
            self.sessions.attach(session)

    def overlay_messages(self, restored_notice: str = "") -> list[Message]:
        if not self.config.enabled:
            return []
        messages: list[Message] = []
        bundle = self.instructions.load()
        self.last_instruction_bundle = bundle
        rendered = bundle.render()
        if rendered:
            messages.append(system_reminder_message(rendered))
        memory_index = self.memories.render_index()
        memory_count = len(self.memories.list_notes())
        if memory_index:
            messages.append(
                system_reminder_message(
                    "MewCode loaded cross-session memory. Use it as background context, "
                    "but re-read files when exact code or current state matters.\n\n"
                    f"{memory_index}"
                )
            )
        notice = restored_notice or self._restore_notice
        if notice:
            messages.append(system_reminder_message(notice))
            self._restore_notice = ""
        self.last_status = {"instructions": bundle.count, "memories": memory_count}
        return messages

    def remember_turn(self, session: ChatSession) -> int:
        if not self.config.enabled or not self.auto_memory_enabled:
            return 0
        note_texts = self._extract_notes(session)
        count = 0
        for category, scope, content in note_texts:
            if self.memories.add_note(category, content, scope=scope) is not None:
                count += 1
        return count

    def status_counts(self) -> dict[str, int]:
        counts = dict(self.last_status)
        counts["sessions"] = len(self.sessions.list_sessions())
        counts["auto_memory_enabled"] = 1 if self.auto_memory_enabled else 0
        return counts

    def command(self, text: str, session: ChatSession) -> str | None:
        stripped = text.strip()
        lowered = stripped.lower()
        if lowered == "/session":
            return "Session commands: /session list, /session current, /session resume <id>, /session delete <id>"
        if lowered == "/session list":
            infos = self.sessions.list_sessions()
            if not infos:
                return "No saved sessions."
            return "\n".join(
                f"- {info.session_id} | {info.message_count} messages | {info.title}" for info in infos[:20]
            )
        if lowered == "/session current":
            return f"Current session: {session.session_id}"
        if lowered.startswith("/session resume "):
            session_id = stripped.split(maxsplit=2)[2].strip()
            if not self.sessions.path_for(session_id).exists():
                return f"Session not found: {session_id}"
            restored = self.sessions.restore(session_id)
            session.session_id = restored.session.session_id
            session.replace_messages(restored.session.snapshot(), reason="resume_session")
            self.attach_session(session)
            self._restore_notice = restored.elapsed_notice
            warnings = f"\nWarnings:\n" + "\n".join(f"- {warning}" for warning in restored.warnings) if restored.warnings else ""
            return f"Restored session {session_id} with {len(session.messages)} messages.{warnings}"
        if lowered.startswith("/session delete "):
            session_id = stripped.split(maxsplit=2)[2].strip()
            return f"Deleted session {session_id}." if self.sessions.delete(session_id) else f"Session not found: {session_id}"
        if lowered.startswith("/session rename "):
            parts = stripped.split(maxsplit=3)
            if len(parts) < 4:
                return "Usage: /session rename <id> <title>"
            session_id = parts[2].strip()
            title = parts[3].strip()
            return f"Renamed session {session_id}." if self.sessions.rename(session_id, title) else f"Session not found: {session_id}"
        if lowered == "/memory":
            return "Memory commands: /memory list, /memory refresh, /memory on, /memory off, /memory delete <id>"
        if lowered == "/memory list":
            notes = self.memories.list_notes()
            if not notes:
                return "No saved memories."
            return "\n".join(f"- {note.memory_id} | {note.scope} | {note.category}: {note.content}" for note in notes[:50])
        if lowered == "/memory refresh":
            self.memories.refresh_index("project")
            self.memories.refresh_index("user")
            return "Memory index refreshed."
        if lowered == "/memory on":
            self.auto_memory_enabled = True
            return "Auto memory enabled."
        if lowered == "/memory off":
            self.auto_memory_enabled = False
            return "Auto memory disabled."
        if lowered.startswith("/memory delete "):
            memory_id = stripped.split(maxsplit=2)[2].strip()
            return f"Deleted memory {memory_id}." if self.memories.delete(memory_id) else f"Memory not found: {memory_id}"
        return None

    def _extract_notes(self, session: ChatSession) -> list[tuple[str, str, str]]:
        user_text = self._last_content(session, "user")
        notes: list[tuple[str, str, str]] = []
        remember_intent = any(marker in user_text for marker in ("记住", "记一下", "请记住", "记录", "以后", "偏好", "习惯", "prefer", "always", "以后都"))
        project_signal = any(marker in user_text for marker in ("本项目", "这个项目", "MewCode", "技术栈", "入口", "架构"))
        user_signal = any(marker in user_text for marker in ("我", "我的", "偏好", "习惯", "prefer", "always", "以后"))
        correction_signal = any(
            marker in user_text
            for marker in ("纠正", "更正", "你错了", "不是这样", "不是这个", "改成", "wrong", "instead")
        ) or ("不是" in user_text and "而是" in user_text)
        reference_signal = any(marker in user_text for marker in ("参考", "链接", "文档", "http://", "https://"))
        if remember_intent and user_signal and not project_signal:
            notes.append(("user_preference", "user", user_text[:600]))
        if correction_signal:
            notes.append(("correction_feedback", "user", user_text[:600]))
        if project_signal and remember_intent:
            notes.append(("project_knowledge", "project", user_text[:800]))
        if reference_signal and remember_intent:
            notes.append(("reference", "project", user_text[:600]))
        return notes

    def _last_content(self, session: ChatSession, role: str) -> str:
        for message in reversed(session.messages):
            if message.get("role") == role:
                return str(message.get("content") or "")
        return ""
