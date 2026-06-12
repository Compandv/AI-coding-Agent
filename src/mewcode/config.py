from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from mewcode.context import ContextConfig
from mewcode.memory import MemoryRuntimeConfig
from mewcode.permissions import DEFAULT_PERMISSION_MODE, PermissionError, PermissionMode, validate_permission_mode


CONFIG_PATH = Path.home() / ".mewcode" / "config.yaml"
PROJECT_CONFIG_PATH = Path(".mewcode.yaml")
LEGACY_PROJECT_CONFIG_PATH = Path(".mewcode") / "config.yaml"
REQUIRED_FIELDS = ("protocol", "model", "base_url", "api_key")
ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(Exception):
    """Raised when the MewCode configuration cannot be loaded."""


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    transport: str
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    read_only_tools: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class MCPConfig:
    servers: dict[str, MCPServerConfig] = field(default_factory=dict)
    skipped_servers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MewCodeConfig:
    protocol: str
    model: str
    base_url: str
    api_key: str
    thinking: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float = 60.0
    max_tool_steps: int = 24
    permission_mode: PermissionMode = DEFAULT_PERMISSION_MODE
    mcp: MCPConfig = field(default_factory=MCPConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    memory: MemoryRuntimeConfig = field(default_factory=MemoryRuntimeConfig)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def normalized_protocol(self) -> str:
        return self.protocol.strip().lower()


def load_config(path: Path | None = None, project_path: Path | None = None) -> MewCodeConfig:
    config_path = path or CONFIG_PATH
    if not config_path.exists():
        raise ConfigError(f"Config file not found. Create {config_path} or ~/.mewcode/config.yaml.")

    raw = normalize_config_aliases(read_config_mapping(config_path))
    if project_path is not None or path is None:
        project_config_path = project_path or find_project_config_path(Path.cwd())
        if project_config_path.exists():
            raw = merge_config_mappings(raw, normalize_config_aliases(read_config_mapping(project_config_path)))

    missing = [field for field in REQUIRED_FIELDS if not raw.get(field)]
    if missing:
        raise ConfigError(f"Config file {config_path} is missing required field(s): {', '.join(missing)}")

    extra = {
        key: value
        for key, value in raw.items()
        if key
        not in {
            *REQUIRED_FIELDS,
            "thinking",
            "timeout_seconds",
            "max_tool_steps",
            "permission_mode",
            "mcp",
            "mcp_servers",
            "context",
            "context_management",
            "context_window",
            "memory",
        }
    }
    timeout = raw.get("timeout_seconds", 60.0)
    try:
        timeout_seconds = float(timeout)
    except (TypeError, ValueError) as exc:
        raise ConfigError("Config field timeout_seconds must be a number.") from exc

    raw_max_tool_steps = raw.get("max_tool_steps", 24)
    try:
        max_tool_steps = int(raw_max_tool_steps)
    except (TypeError, ValueError) as exc:
        raise ConfigError("Config field max_tool_steps must be a positive integer.") from exc
    if max_tool_steps < 1:
        raise ConfigError("Config field max_tool_steps must be a positive integer.")

    thinking = raw.get("thinking") or {}
    if not isinstance(thinking, dict):
        raise ConfigError("Config field thinking must be a mapping when provided.")

    try:
        permission_mode = validate_permission_mode(raw.get("permission_mode"))
    except PermissionError as exc:
        raise ConfigError(str(exc)) from exc
    mcp = normalize_mcp_config(raw.get("mcp"))
    context = normalize_context_config(_merged_context_options(raw))
    memory = normalize_memory_config(raw.get("memory"))

    return MewCodeConfig(
        protocol=str(raw["protocol"]),
        model=str(raw["model"]),
        base_url=str(raw["base_url"]).rstrip("/"),
        api_key=str(raw["api_key"]),
        thinking=thinking,
        timeout_seconds=timeout_seconds,
        max_tool_steps=max_tool_steps,
        permission_mode=permission_mode,
        mcp=mcp,
        context=context,
        memory=memory,
        extra=extra,
    )


def read_config_mapping(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Failed to parse config file {path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Failed to read config file {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"Config file {path} must contain a YAML mapping.")
    return raw


def find_project_config_path(cwd: Path) -> Path:
    current_path = cwd / PROJECT_CONFIG_PATH
    if current_path.exists():
        return current_path
    return cwd / LEGACY_PROJECT_CONFIG_PATH


def normalize_config_aliases(raw: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(raw)
    mcp_servers = normalized.pop("mcp_servers", None)
    if mcp_servers is None:
        return normalized

    alias_mcp = {"servers": mcp_servers}
    current_mcp = normalized.get("mcp")
    if current_mcp is None:
        normalized["mcp"] = alias_mcp
    elif isinstance(current_mcp, dict):
        normalized["mcp"] = merge_mcp_mappings(alias_mcp, current_mcp)
    return normalized


def merge_config_mappings(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if key == "mcp" and isinstance(value, dict) and isinstance(merged.get("mcp"), dict):
            merged[key] = merge_mcp_mappings(dict(merged["mcp"]), value)
        else:
            merged[key] = value
    return merged


def merge_mcp_mappings(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    base_servers = base.get("servers")
    overlay_servers = overlay.get("servers")
    if isinstance(base_servers, dict) or isinstance(overlay_servers, dict):
        servers: dict[str, Any] = {}
        if isinstance(base_servers, dict):
            servers.update(base_servers)
        if isinstance(overlay_servers, dict):
            servers.update(overlay_servers)
        merged["servers"] = servers
    for key, value in overlay.items():
        if key != "servers":
            merged[key] = value
    return merged


def normalize_mcp_config(raw: Any) -> MCPConfig:
    if raw in (None, {}):
        return MCPConfig()
    if not isinstance(raw, dict):
        raise ConfigError("Config field mcp must be a mapping when provided.")
    raw_servers = raw.get("servers") or {}
    if not isinstance(raw_servers, dict):
        raise ConfigError("Config field mcp.servers must be a mapping when provided.")

    servers: dict[str, MCPServerConfig] = {}
    skipped: dict[str, str] = {}
    for name, raw_server in raw_servers.items():
        server_name = str(name).strip()
        if not server_name:
            raise ConfigError("MCP server name cannot be empty.")
        if not isinstance(raw_server, dict):
            raise ConfigError(f"MCP server {server_name} must be a mapping.")
        try:
            server = normalize_mcp_server(server_name, raw_server)
        except MissingEnvironmentVariable as exc:
            skipped[server_name] = str(exc)
            continue
        servers[server_name] = server
    return MCPConfig(servers=servers, skipped_servers=skipped)


def normalize_context_config(raw: Any) -> ContextConfig:
    if raw in (None, {}):
        return ContextConfig()
    if not isinstance(raw, dict):
        raise ConfigError("Config field context must be a mapping when provided.")

    defaults = ContextConfig()
    aliases = {
        "context_window": "context_window_tokens",
        "auto_margin": "auto_margin_tokens",
        "manual_margin": "manual_margin_tokens",
        "recent_tokens": "recent_token_target",
        "single_result_tokens": "single_result_token_threshold",
        "aggregate_result_tokens": "aggregate_result_token_threshold",
        "single_result_bytes": "single_result_byte_threshold",
        "aggregate_result_bytes": "aggregate_result_byte_threshold",
        "summary_failure_limit": "max_summary_failures",
        "summary_chunk_target": "summary_chunk_target_tokens",
        "summary_chunk_max": "summary_chunk_max_tokens",
        "tool_preview_head": "tool_preview_head_chars",
        "tool_preview_tail": "tool_preview_tail_chars",
        "compact_focus_max": "compact_focus_max_chars",
    }
    values: dict[str, Any] = {}
    valid_fields = set(defaults.__dataclass_fields__)  # type: ignore[attr-defined]
    for key, value in raw.items():
        normalized_key = aliases.get(str(key), str(key))
        if normalized_key not in valid_fields:
            values[normalized_key] = value
            continue
        if normalized_key == "cache_dir":
            values[normalized_key] = str(value)
            continue
        values[normalized_key] = _positive_int(value, f"context.{normalized_key}")
    try:
        return ContextConfig(**values)
    except TypeError as exc:
        raise ConfigError(f"Invalid context configuration: {exc}") from exc


def normalize_memory_config(raw: Any) -> MemoryRuntimeConfig:
    if raw in (None, {}):
        return MemoryRuntimeConfig()
    if not isinstance(raw, dict):
        raise ConfigError("Config field memory must be a mapping when provided.")

    defaults = MemoryRuntimeConfig()
    values: dict[str, Any] = {}
    aliases = {
        "auto_memory": "auto_extract",
        "retention_days": "session_retention_days",
        "include_depth": "include_max_depth",
        "memory_index_lines": "index_max_lines",
        "memory_index_bytes": "index_max_bytes",
    }
    valid_fields = set(defaults.__dataclass_fields__)  # type: ignore[attr-defined]
    for key, value in raw.items():
        normalized_key = aliases.get(str(key), str(key))
        if normalized_key not in valid_fields:
            continue
        if isinstance(getattr(defaults, normalized_key), bool):
            values[normalized_key] = _bool_value(value, f"memory.{normalized_key}")
        else:
            values[normalized_key] = _positive_int(value, f"memory.{normalized_key}")
    try:
        return MemoryRuntimeConfig(**values)
    except TypeError as exc:
        raise ConfigError(f"Invalid memory configuration: {exc}") from exc


def _merged_context_options(raw: dict[str, Any]) -> Any:
    context_raw = raw.get("context") or raw.get("context_management")
    if raw.get("context_window") is None:
        return context_raw
    if context_raw in (None, {}):
        context_raw = {}
    if not isinstance(context_raw, dict):
        return context_raw
    merged = dict(context_raw)
    merged.setdefault("context_window_tokens", raw["context_window"])
    return merged


def _positive_int(value: Any, field_name: str) -> int:
    try:
        integer = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Config field {field_name} must be a positive integer.") from exc
    if integer < 1:
        raise ConfigError(f"Config field {field_name} must be a positive integer.")
    return integer


def _bool_value(value: Any, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "on", "1"}:
            return True
        if normalized in {"false", "no", "off", "0"}:
            return False
    raise ConfigError(f"Config field {field_name} must be a boolean.")


def normalize_mcp_server(name: str, raw: dict[str, Any]) -> MCPServerConfig:
    transport = str(raw.get("transport") or raw.get("type") or "").strip().lower()
    if transport not in {"stdio", "http"}:
        raise ConfigError(f"MCP server {name} must set transport/type to stdio or http.")

    read_only_tools = raw.get("read_only_tools") or []
    if not isinstance(read_only_tools, list):
        raise ConfigError(f"MCP server {name} read_only_tools must be a list.")
    if transport == "stdio":
        command = str(raw.get("command") or "").strip()
        if not command:
            raise ConfigError(f"MCP stdio server {name} must set command.")
        args = raw.get("args") or []
        if not isinstance(args, list):
            raise ConfigError(f"MCP stdio server {name} args must be a list.")
        raw_env = raw.get("env") or {}
        if not isinstance(raw_env, dict):
            raise ConfigError(f"MCP stdio server {name} env must be a mapping.")
        return MCPServerConfig(
            name=name,
            transport=transport,
            command=command,
            args=[str(expand_env_value(value)) for value in args],
            env={str(key): str(expand_env_value(value)) for key, value in raw_env.items()},
            read_only_tools={str(tool) for tool in read_only_tools},
        )

    url = str(raw.get("url") or "").strip()
    if not url:
        raise ConfigError(f"MCP HTTP server {name} must set url.")
    raw_headers = raw.get("headers") or {}
    if not isinstance(raw_headers, dict):
        raise ConfigError(f"MCP HTTP server {name} headers must be a mapping.")
    return MCPServerConfig(
        name=name,
        transport=transport,
        url=str(expand_env_value(url)),
        headers={str(key): str(expand_env_value(value)) for key, value in raw_headers.items()},
        read_only_tools={str(tool) for tool in read_only_tools},
    )


class MissingEnvironmentVariable(Exception):
    """Raised internally when an MCP server references a missing environment variable."""


def expand_env_value(value: Any) -> str:
    text = str(value)

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in os.environ:
            raise MissingEnvironmentVariable(f"Missing environment variable: {name}")
        return os.environ[name]

    return ENV_PATTERN.sub(replace, text)
