from __future__ import annotations


class ProviderError(Exception):
    """Raised when a model provider request fails."""


class PromptTooLongError(ProviderError):
    """Raised when a provider rejects a request for exceeding the context window."""


def is_prompt_too_long_message(message: str) -> bool:
    lowered = message.lower()
    patterns = [
        "prompt_too_long",
        "context_length_exceeded",
        "context length",
        "maximum context",
        "context window",
        "too many tokens",
        "input is too long",
        "prompt is too long",
    ]
    return any(pattern in lowered for pattern in patterns)
