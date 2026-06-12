from pathlib import Path

import pytest

from mewcode.config import ConfigError, load_config


def write_config(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_load_config_accepts_required_and_extra_fields(tmp_path):
    path = write_config(
        tmp_path / "config.yaml",
        """
protocol: anthropic
model: claude-sonnet-4-6
base_url: https://api.anthropic.com/
api_key: sk-ant-placeholder
thinking:
  enabled: true
  budget_tokens: 1024
timeout_seconds: 12
max_tool_steps: 32
permission_mode: acceptEdits
custom: value
""",
    )

    config = load_config(path)

    assert config.protocol == "anthropic"
    assert config.model == "claude-sonnet-4-6"
    assert config.base_url == "https://api.anthropic.com"
    assert config.api_key == "sk-ant-placeholder"
    assert config.thinking == {"enabled": True, "budget_tokens": 1024}
    assert config.timeout_seconds == 12
    assert config.max_tool_steps == 32
    assert config.permission_mode == "acceptEdits"
    assert config.extra == {"custom": "value"}


def test_load_config_parses_mcp_servers_and_expands_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
    path = write_config(
        tmp_path / "config.yaml",
        """
protocol: openai
model: gpt-4.1
base_url: https://api.openai.com/v1
api_key: secret
mcp:
  servers:
    github:
      transport: stdio
      command: npx
      args: ["-y", "@modelcontextprotocol/server-github"]
      env:
        GITHUB_TOKEN: "${GITHUB_TOKEN}"
      read_only_tools: ["list_issues"]
    remote:
      transport: http
      url: "https://example.test/mcp"
      headers:
        Authorization: "Bearer ${GITHUB_TOKEN}"
""",
    )

    config = load_config(path)

    assert set(config.mcp.servers) == {"github", "remote"}
    assert config.mcp.servers["github"].env == {"GITHUB_TOKEN": "gh-token"}
    assert config.mcp.servers["github"].read_only_tools == {"list_issues"}
    assert config.mcp.servers["remote"].headers == {"Authorization": "Bearer gh-token"}


def test_load_config_skips_mcp_server_when_env_missing(tmp_path):
    path = write_config(
        tmp_path / "config.yaml",
        """
protocol: openai
model: gpt-4.1
base_url: https://api.openai.com/v1
api_key: secret
mcp:
  servers:
    github:
      transport: stdio
      command: npx
      env:
        GITHUB_TOKEN: "${MISSING_GITHUB_TOKEN}"
""",
    )

    config = load_config(path)

    assert config.mcp.servers == {}
    assert "github" in config.mcp.skipped_servers
    assert "MISSING_GITHUB_TOKEN" in config.mcp.skipped_servers["github"]


def test_load_config_merges_project_mcp_servers_by_name(tmp_path):
    user_config = write_config(
        tmp_path / "user.yaml",
        """
protocol: openai
model: gpt-4.1
base_url: https://api.openai.com/v1
api_key: secret
mcp:
  servers:
    github:
      transport: stdio
      command: old
    slack:
      transport: http
      url: https://slack.example.test/mcp
""",
    )
    project_config = write_config(
        tmp_path / "project.yaml",
        """
mcp:
  servers:
    github:
      transport: stdio
      command: new
      read_only_tools: ["list_issues"]
""",
    )

    config = load_config(user_config, project_path=project_config)

    assert set(config.mcp.servers) == {"github", "slack"}
    assert config.mcp.servers["github"].command == "new"
    assert config.mcp.servers["github"].read_only_tools == {"list_issues"}
    assert config.mcp.servers["slack"].url == "https://slack.example.test/mcp"


def test_load_config_uses_project_mewcode_yaml_and_aliases(tmp_path, monkeypatch):
    user_config = write_config(
        tmp_path / "user.yaml",
        """
protocol: openai
model: gpt-4.1
base_url: https://api.openai.com/v1
api_key: secret
mcp_servers:
  context7:
    type: stdio
    command: old-context7
  github:
    type: http
    url: https://github.example.test/mcp
""",
    )
    write_config(
        tmp_path / ".mewcode.yaml",
        """
mcp_servers:
  context7:
    type: stdio
    command: npx
    args: ["-y", "@upstash/context7-mcp"]
""",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("mewcode.config.CONFIG_PATH", user_config)

    config = load_config()

    assert set(config.mcp.servers) == {"context7", "github"}
    assert config.mcp.servers["context7"].transport == "stdio"
    assert config.mcp.servers["context7"].command == "npx"
    assert config.mcp.servers["context7"].args == ["-y", "@upstash/context7-mcp"]
    assert config.mcp.servers["github"].transport == "http"


def test_load_config_uses_default_max_tool_steps(tmp_path):
    path = write_config(
        tmp_path / "config.yaml",
        """
protocol: openai
model: gpt-4.1
base_url: https://api.openai.com/v1
api_key: secret
""",
    )

    config = load_config(path)

    assert config.max_tool_steps == 24
    assert config.permission_mode == "default"
    assert config.context.context_window_tokens == 128000
    assert config.context.single_result_byte_threshold == 50000
    assert config.memory.auto_extract is True
    assert config.memory.session_retention_days == 30


def test_load_config_parses_context_management_options(tmp_path):
    path = write_config(
        tmp_path / "config.yaml",
        """
protocol: openai
model: gpt-4.1
base_url: https://api.openai.com/v1
api_key: secret
context:
  context_window_tokens: 64000
  auto_margin_tokens: 12000
  manual_margin_tokens: 2000
  single_result_bytes: 40000
  aggregate_result_bytes: 180000
  preview_chars: 1500
  tool_preview_head_chars: 3000
  tool_preview_tail_chars: 2500
  summary_chunk_target_tokens: 9000
  summary_chunk_max_tokens: 14000
  compact_focus_max_chars: 800
  cache_dir: .mewcode/custom-context
""",
    )

    config = load_config(path)

    assert config.context.context_window_tokens == 64000
    assert config.context.auto_margin_tokens == 12000
    assert config.context.manual_margin_tokens == 2000
    assert config.context.single_result_byte_threshold == 40000
    assert config.context.aggregate_result_byte_threshold == 180000
    assert config.context.preview_chars == 1500
    assert config.context.tool_preview_head_chars == 3000
    assert config.context.tool_preview_tail_chars == 2500
    assert config.context.summary_chunk_target_tokens == 9000
    assert config.context.summary_chunk_max_tokens == 14000
    assert config.context.compact_focus_max_chars == 800
    assert config.context.cache_dir == ".mewcode/custom-context"


def test_load_config_accepts_top_level_context_window(tmp_path):
    path = write_config(
        tmp_path / "config.yaml",
        """
protocol: openai
model: gpt-4.1
base_url: https://api.openai.com/v1
api_key: secret
context_window: 96000
""",
    )

    config = load_config(path)

    assert config.context.context_window_tokens == 96000


def test_load_config_reports_invalid_context_option(tmp_path):
    path = write_config(
        tmp_path / "config.yaml",
        """
protocol: openai
model: gpt-4.1
base_url: https://api.openai.com/v1
api_key: secret
context:
  auto_margin_tokens: 0
""",
    )

    with pytest.raises(ConfigError) as exc_info:
        load_config(path)

    assert "context.auto_margin_tokens" in str(exc_info.value)


def test_load_config_parses_memory_options(tmp_path):
    path = write_config(
        tmp_path / "config.yaml",
        """
protocol: openai
model: gpt-4.1
base_url: https://api.openai.com/v1
api_key: secret
memory:
  enabled: true
  auto_memory: false
  retention_days: 14
  include_depth: 3
  memory_index_lines: 120
  memory_index_bytes: 12000
""",
    )

    config = load_config(path)

    assert config.memory.enabled is True
    assert config.memory.auto_extract is False
    assert config.memory.session_retention_days == 14
    assert config.memory.include_max_depth == 3
    assert config.memory.index_max_lines == 120
    assert config.memory.index_max_bytes == 12000


def test_load_config_reports_invalid_permission_mode(tmp_path):
    path = write_config(
        tmp_path / "config.yaml",
        """
protocol: openai
model: gpt-4.1
base_url: https://api.openai.com/v1
api_key: secret
permission_mode: reckless
""",
    )

    with pytest.raises(ConfigError) as exc_info:
        load_config(path)

    assert "permission mode" in str(exc_info.value)


def test_load_config_reports_invalid_max_tool_steps(tmp_path):
    path = write_config(
        tmp_path / "config.yaml",
        """
protocol: openai
model: gpt-4.1
base_url: https://api.openai.com/v1
api_key: secret
max_tool_steps: 0
""",
    )

    with pytest.raises(ConfigError) as exc_info:
        load_config(path)

    assert "max_tool_steps" in str(exc_info.value)


def test_load_config_reports_missing_fields(tmp_path):
    path = write_config(tmp_path / "config.yaml", "protocol: openai\n")

    with pytest.raises(ConfigError) as exc_info:
        load_config(path)

    message = str(exc_info.value)
    assert "model" in message
    assert "base_url" in message
    assert "api_key" in message


def test_load_config_reports_missing_file(tmp_path):
    with pytest.raises(ConfigError) as exc_info:
        load_config(tmp_path / "missing.yaml")

    assert "~/.mewcode/config.yaml" in str(exc_info.value)
