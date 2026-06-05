from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .base import ToolError


@dataclass(frozen=True)
class ToolContext:
    root_dir: Path
    timeout_seconds: float = 15.0
    max_output_chars: int = 12000

    def resolve_path(self, raw_path: str) -> Path:
        candidate = Path(raw_path)
        resolved = (self.root_dir / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        try:
            resolved.relative_to(self.root_dir.resolve())
        except ValueError as exc:
            raise ToolError(f"Path is outside the allowed workspace: {raw_path}") from exc
        return resolved

    def truncate_output(self, text: str) -> str:
        if len(text) <= self.max_output_chars:
            return text
        return text[: self.max_output_chars] + "\n...[truncated]"
