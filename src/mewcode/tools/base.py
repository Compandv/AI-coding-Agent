from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolParameter:
    type: str
    description: str
    items: dict[str, Any] | None = None


@dataclass(frozen=True)
class ToolSchema:
    type: str = "object"
    properties: dict[str, ToolParameter] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)

    def to_model_dict(self) -> dict[str, Any]:
        def parameter_dict(parameter: ToolParameter) -> dict[str, Any]:
            payload = {"type": parameter.type, "description": parameter.description}
            if parameter.items is not None:
                payload["items"] = parameter.items
            return payload

        return {
            "type": self.type,
            "properties": {
                name: parameter_dict(parameter) for name, parameter in self.properties.items()
            },
            "required": list(self.required),
        }


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    schema: ToolSchema
    requires_confirmation: bool = False

    def to_model_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.schema.to_model_dict(),
        }


@dataclass
class ToolResult:
    ok: bool
    content: str = ""
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_message_content(self) -> dict[str, Any]:
        payload = {
            "ok": self.ok,
            "content": self.content,
            "metadata": self.metadata,
        }
        if self.error is not None:
            payload["error"] = self.error
        return payload


class ToolError(Exception):
    """Raised when a tool cannot complete successfully."""


class Tool(ABC):
    definition: ToolDefinition

    @abstractmethod
    def execute(self, arguments: dict[str, Any], context: "ToolContext") -> ToolResult:
        """Execute the tool with validated arguments."""
