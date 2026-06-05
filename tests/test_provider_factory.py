from mewcode.config import MewCodeConfig
from mewcode.providers import AnthropicProvider, OpenAIProvider, ProviderError, create_provider


def config(protocol: str) -> MewCodeConfig:
    return MewCodeConfig(
        protocol=protocol,
        model="model",
        base_url="https://example.test",
        api_key="secret",
    )


def test_create_anthropic_provider():
    assert isinstance(create_provider(config("anthropic")), AnthropicProvider)


def test_create_openai_provider():
    assert isinstance(create_provider(config("openai")), OpenAIProvider)


def test_unknown_protocol_mentions_value():
    try:
        create_provider(config("unknown"))
    except ProviderError as exc:
        assert "unknown" in str(exc)
    else:
        raise AssertionError("Expected ProviderError")
