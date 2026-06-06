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
    assert config.extra == {"custom": "value"}


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
