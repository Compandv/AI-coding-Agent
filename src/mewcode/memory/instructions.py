from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re


INCLUDE_PATTERN = re.compile(r"^\s*@include\s+(.+?)\s*$")


@dataclass(frozen=True)
class InstructionFile:
    path: Path
    scope: str
    priority: int
    content: str
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class InstructionBundle:
    files: list[InstructionFile]
    warnings: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.files)

    def render(self) -> str:
        if not self.files:
            return ""
        parts = ["MewCode loaded project and user instruction files. Follow higher-priority sections first."]
        for file in self.files:
            parts.append(f"\n## {file.scope}: {file.path}\n{file.content.strip()}")
        if self.warnings:
            warning_lines = "\n".join(f"- {warning}" for warning in self.warnings)
            parts.append(f"\n## Instruction loading warnings\n{warning_lines}")
        return "\n".join(parts).strip()


class InstructionLoader:
    def __init__(self, project_root: Path, user_home: Path | None = None, max_include_depth: int = 5) -> None:
        self.project_root = project_root.resolve()
        self.user_home = (user_home or Path.home()).resolve()
        self.max_include_depth = max_include_depth

    def load(self) -> InstructionBundle:
        specs = [
            (self.project_root / ".mewcode" / "MEWCODE.md", "Project private instructions", 10, self.project_root),
            (self.project_root / "MEWCODE.md", "Project root instructions", 20, self.project_root),
            (self.user_home / ".mewcode" / "MEWCODE.md", "User global instructions", 30, self.user_home),
        ]
        files: list[InstructionFile] = []
        warnings: list[str] = []
        for path, scope, priority, allowed_root in specs:
            if not path.exists():
                continue
            try:
                content, file_warnings = self._read_with_includes(
                    path.resolve(),
                    allowed_root.resolve(),
                    depth=0,
                    visited=set(),
                )
            except OSError as exc:
                warnings.append(f"Failed to read {path}: {exc}")
                continue
            warnings.extend(file_warnings)
            files.append(InstructionFile(path=path, scope=scope, priority=priority, content=content, warnings=file_warnings))
        return InstructionBundle(files=sorted(files, key=lambda item: item.priority), warnings=warnings)

    def _read_with_includes(
        self,
        path: Path,
        allowed_root: Path,
        *,
        depth: int,
        visited: set[Path],
    ) -> tuple[str, list[str]]:
        warnings: list[str] = []
        resolved = path.resolve()
        if not self._is_relative_to(resolved, allowed_root):
            return "", [f"Blocked include outside allowed root: {path}"]
        if resolved in visited:
            return "", [f"Skipped cyclic include: {path}"]
        if depth > self.max_include_depth:
            return "", [f"Skipped include beyond max depth {self.max_include_depth}: {path}"]
        visited.add(resolved)
        try:
            lines = resolved.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            return "", [f"Failed to read include {path}: {exc}"]

        output: list[str] = []
        for line in lines:
            match = INCLUDE_PATTERN.match(line)
            if match is None:
                output.append(line)
                continue
            include_text = match.group(1).strip().strip("\"'")
            include_path = (resolved.parent / include_text).resolve()
            if not include_path.exists():
                warnings.append(f"Missing include file: {include_path}")
                continue
            included, nested_warnings = self._read_with_includes(
                include_path,
                allowed_root,
                depth=depth + 1,
                visited=visited,
            )
            warnings.extend(nested_warnings)
            if included:
                output.append(f"\n<!-- included from {include_path} -->")
                output.append(included)
                output.append(f"<!-- end include {include_path} -->\n")
        visited.remove(resolved)
        return "\n".join(output), warnings

    def _is_relative_to(self, path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
        except ValueError:
            return False
        return True
