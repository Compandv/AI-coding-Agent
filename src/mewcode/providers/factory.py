from __future__ import annotations

from mewcode.config import MewCodeConfig

from .anthropic import AnthropicProvider
from .base import ChatProvider
from .errors import ProviderError
from .openai import OpenAIProvider


def create_provider(config: MewCodeConfig) -> ChatProvider:
    protocol = config.normalized_protocol
    if protocol in {"anthropic", "claude"}:
        return AnthropicProvider(config)
    if protocol == "openai":
        return OpenAIProvider(config)
    raise ProviderError(f"Unsupported protocol: {config.protocol}")
