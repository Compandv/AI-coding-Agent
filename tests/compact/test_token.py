import math

from mewcode.compact.token import estimate_tokens, message_chars, usage_anchor
from mewcode.providers.base import ProviderUsage


def test_estimate_tokens_uses_anchor_and_tail_delta():
    messages = [
        {"role": "user", "content": "a" * 35},
        {"role": "assistant", "content": "b" * 35},
    ]

    assert estimate_tokens(100, messages, 1) == 100 + math.ceil(message_chars(messages[1:]) / 3.5)


def test_usage_anchor_sums_provider_usage_fields():
    usage = ProviderUsage(
        input_tokens=10,
        output_tokens=20,
        cache_read_input_tokens=30,
        cache_creation_input_tokens=40,
    )

    assert usage_anchor(usage) == 100
