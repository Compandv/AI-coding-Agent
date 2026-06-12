from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
import secrets


SECRET_PATTERNS = (
    re.compile(r"(?i)\b(api[_-]?key|secret|token|password)\b\s*[:=]"),
    re.compile(r"(?i)\.env\b"),
)


@dataclass(frozen=True)
class MemoryNote:
    memory_id: str
    category: str
    scope: str
    content: str
    path: Path


class MemoryStore:
    def __init__(self, project_root: Path, user_home: Path | None = None, index_max_lines: int = 200, index_max_bytes: int = 25_000) -> None:
        self.project_root = project_root.resolve()
        self.user_home = (user_home or Path.home()).resolve()
        self.project_dir = self.project_root / ".mewcode" / "memory"
        self.user_dir = self.user_home / ".mewcode" / "memory"
        self.index_max_lines = index_max_lines
        self.index_max_bytes = index_max_bytes

    def add_note(self, category: str, content: str, scope: str = "project") -> MemoryNote | None:
        normalized = " ".join(content.split()).strip()
        if not normalized or self._looks_sensitive(normalized):
            return None
        if self._has_note(category, normalized, scope):
            return None
        directory = self.project_dir if scope == "project" else self.user_dir
        directory.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        memory_id = f"{now.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}-{category}"
        path = directory / f"{memory_id}.md"
        markdown = (
            "---\n"
            f"id: {memory_id}\n"
            f"category: {category}\n"
            f"scope: {scope}\n"
            f"created_at: {now.isoformat()}\n"
            "---\n\n"
            f"{normalized}\n"
        )
        path.write_text(markdown, encoding="utf-8")
        self.refresh_index(scope)
        return MemoryNote(memory_id=memory_id, category=category, scope=scope, content=normalized, path=path)

    def list_notes(self, scope: str | None = None) -> list[MemoryNote]:
        directories: list[tuple[str, Path]] = []
        if scope in (None, "project"):
            directories.append(("project", self.project_dir))
        if scope in (None, "user"):
            directories.append(("user", self.user_dir))
        notes: list[MemoryNote] = []
        for note_scope, directory in directories:
            if not directory.exists():
                continue
            for path in sorted(directory.glob("*.md")):
                if path.name == "index.md":
                    continue
                note = self._read_note(path, note_scope)
                if note is not None:
                    notes.append(note)
        return sorted(notes, key=lambda note: note.memory_id, reverse=True)

    def delete(self, memory_id: str) -> bool:
        deleted = False
        for directory in (self.project_dir, self.user_dir):
            path = directory / f"{memory_id}.md"
            if path.exists():
                path.unlink()
                deleted = True
        if deleted:
            self.refresh_index("project")
            self.refresh_index("user")
        return deleted

    def refresh_index(self, scope: str = "project") -> str:
        directory = self.project_dir if scope == "project" else self.user_dir
        directory.mkdir(parents=True, exist_ok=True)
        notes = self.list_notes(scope)
        lines = [f"# {scope.title()} Memory Index", ""]
        for note in notes:
            lines.append(f"- [{note.category}] {note.content}")
        content = "\n".join(lines[: self.index_max_lines])
        while len(content.encode("utf-8")) > self.index_max_bytes and len(lines) > 2:
            lines.pop()
            content = "\n".join(lines[: self.index_max_lines])
        (directory / "index.md").write_text(content + "\n", encoding="utf-8")
        return content

    def render_index(self) -> str:
        parts: list[str] = []
        for scope, directory in (("project", self.project_dir), ("user", self.user_dir)):
            index_path = directory / "index.md"
            if not index_path.exists():
                has_notes = directory.exists() and any(path.name != "index.md" for path in directory.glob("*.md"))
                if not has_notes:
                    continue
                self.refresh_index(scope)
            if index_path.exists():
                content = index_path.read_text(encoding="utf-8").strip()
                if content and not content.endswith("Memory Index"):
                    parts.append(content)
        return "\n\n".join(parts).strip()

    def _read_note(self, path: Path, scope: str) -> MemoryNote | None:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None
        category = "project_knowledge"
        content = text
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) == 3:
                frontmatter = parts[1]
                content = parts[2].strip()
                for line in frontmatter.splitlines():
                    if line.startswith("category:"):
                        category = line.split(":", 1)[1].strip()
                    if line.startswith("scope:"):
                        scope = line.split(":", 1)[1].strip()
        return MemoryNote(path.stem, category, scope, " ".join(content.split()), path)

    def _has_note(self, category: str, content: str, scope: str) -> bool:
        return any(
            note.category == category and note.content == content and note.scope == scope
            for note in self.list_notes(scope)
        )

    def _looks_sensitive(self, text: str) -> bool:
        return any(pattern.search(text) for pattern in SECRET_PATTERNS)
