from __future__ import annotations

import random
import secrets
import threading
import time
from copy import copy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal

from .const import MAX_CONSECUTIVE_AUTO_COMPACT_FAILURES

ReplacementKind = Literal["kept", "replaced", "skip"]


@dataclass(frozen=True)
class SessionContext:
    session_id: str
    spill_dir: str


def new_session_id() -> str:
    try:
        suffix = secrets.token_hex(4)
    except Exception:
        suffix = random.Random(time.time()).randbytes(4).hex()
    return f"{int(time.time())}-{suffix}"


def new_session_context(workspace: str | Path) -> SessionContext:
    session_id = new_session_id()
    spill_dir = Path(workspace) / ".mewcode" / "sessions" / session_id / "tool-results"
    spill_dir.mkdir(parents=True, exist_ok=True)
    return SessionContext(session_id=session_id, spill_dir=str(spill_dir))


class ContentReplacementState:
    """Session-level ledger for deterministic tool result replacement."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._seen_ids: set[str] = set()
        self._replacements: dict[str, str] = {}

    def decide_once(
        self,
        tool_use_id: str,
        original: str,
        decide: Callable[[], tuple[ReplacementKind, str]],
    ) -> str:
        with self._lock:
            if tool_use_id in self._seen_ids:
                return self._replacements.get(tool_use_id, original)

            decision, preview = decide()
            if decision == "skip":
                return original
            self._seen_ids.add(tool_use_id)
            if decision == "replaced":
                self._replacements[tool_use_id] = preview
                return preview
            return original

    def replacement_for(self, tool_use_id: str) -> str | None:
        with self._lock:
            return self._replacements.get(tool_use_id)

    def has_seen(self, tool_use_id: str) -> bool:
        with self._lock:
            return tool_use_id in self._seen_ids


class AutoCompactTrackingState:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._consecutive_failures = 0

    @property
    def consecutive_failures(self) -> int:
        with self._lock:
            return self._consecutive_failures

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1

    def tripped(self) -> bool:
        with self._lock:
            return self._consecutive_failures >= MAX_CONSECUTIVE_AUTO_COMPACT_FAILURES


@dataclass(frozen=True)
class FileReadRecord:
    path: str
    content: str
    timestamp: datetime


class RecoveryState:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._files: dict[str, FileReadRecord] = {}

    def record_file(self, path: str | Path, content: str) -> None:
        resolved = str(Path(path).resolve())
        with self._lock:
            self._files[resolved] = FileReadRecord(
                path=resolved,
                content=content,
                timestamp=datetime.now(),
            )

    def snapshot(self) -> list[FileReadRecord]:
        with self._lock:
            records = [copy(record) for record in self._files.values()]
        return sorted(records, key=lambda record: record.timestamp, reverse=True)
