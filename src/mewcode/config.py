from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


CONFIG_PATH = Path.home() / ".mewcode" / "config.yaml"
REQUIRED_FIELDS = ("protocol", "model", "base_url", "api_key")


class ConfigError(Exception):
    """Raised when the MewCode configuration cannot be loaded."""


@dataclass(frozen=True)
class MewCodeConfig:
    protocol: str
    model: str
    base_url: str
    api_key: str
    thinking: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float = 60.0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def normalized_protocol(self) -> str:
        return self.protocol.strip().lower()


def load_config(path: Path | None = None) -> MewCodeConfig:
    config_path = path or CONFIG_PATH
    if not config_path.exists():
        raise ConfigError(f"Config file not found. Create {config_path} or ~/.mewcode/config.yaml.")

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Failed to parse config file {config_path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Failed to read config file {config_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"Config file {config_path} must contain a YAML mapping.")

    missing = [field for field in REQUIRED_FIELDS if not raw.get(field)]
    if missing:
        raise ConfigError(f"Config file {config_path} is missing required field(s): {', '.join(missing)}")

    extra = {key: value for key, value in raw.items() if key not in {*REQUIRED_FIELDS, "thinking", "timeout_seconds"}}
    timeout = raw.get("timeout_seconds", 60.0)
    try:
        timeout_seconds = float(timeout)
    except (TypeError, ValueError) as exc:
        raise ConfigError("Config field timeout_seconds must be a number.") from exc

    thinking = raw.get("thinking") or {}
    if not isinstance(thinking, dict):
        raise ConfigError("Config field thinking must be a mapping when provided.")

    return MewCodeConfig(
        protocol=str(raw["protocol"]),
        model=str(raw["model"]),
        base_url=str(raw["base_url"]).rstrip("/"),
        api_key=str(raw["api_key"]),
        thinking=thinking,
        timeout_seconds=timeout_seconds,
        extra=extra,
    )
