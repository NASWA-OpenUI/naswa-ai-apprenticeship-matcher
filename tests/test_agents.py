import pytest

import naswa_matcher.agents as agents
from naswa_matcher.agents import (
    CHAT_SYSTEM_PROMPT,
    MODEL_CONFIGS,
    REQUESTED_MAX_OUTPUT_TOKENS,
    get_model_config,
    make_bedrock_model,
    make_chat_agent,
    make_scoring_model,
)


@pytest.mark.parametrize(
    ("model_name", "expected_model_id", "expected_max_tokens"),
    [
        (
            "sonnet-4.6",
            "us.anthropic.claude-sonnet-4-6",
            REQUESTED_MAX_OUTPUT_TOKENS,
        ),
        (
            "nova-lite",
            "us.amazon.nova-lite-v1:0",
            10_000,
        ),
        (
            "nova-2-lite",
            "us.amazon.nova-2-lite-v1:0",
            REQUESTED_MAX_OUTPUT_TOKENS,
        ),
    ],
)
def test_get_model_config_returns_supported_model_configuration(
    model_name,
    expected_model_id,
    expected_max_tokens,
):
    config = get_model_config(model_name)

    assert config.model_id == expected_model_id
    assert config.max_output_tokens == expected_max_tokens
    assert config.temperature == 0.0


def test_nova_lite_uses_ten_thousand_output_token_limit():
    assert MODEL_CONFIGS["nova-lite"].max_output_tokens == 10_000


def test_get_model_config_rejects_unsupported_model_name():
    with pytest.raises(ValueError) as exc_info:
        get_model_config("unknown-model")

    message = str(exc_info.value)

    assert "Unsupported model name 'unknown-model'" in message
    assert "nova-lite" in message
    assert "nova-2-lite" in message
    assert "sonnet-4.6" in message


def test_make_bedrock_model_uses_model_configuration(monkeypatch):
    captured = {}

    def fake_bedrock_model(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(agents, "BedrockModel", fake_bedrock_model)

    result = make_bedrock_model(
        "sonnet-4.6",
        streaming=True,
    )

    assert result is not None
    assert captured == {
        "model_id": "us.anthropic.claude-sonnet-4-6",
        "max_tokens": REQUESTED_MAX_OUTPUT_TOKENS,
        "temperature": 0.0,
        "streaming": True,
    }


def test_make_bedrock_model_uses_temperature_override(monkeypatch):
    captured = {}

    def fake_bedrock_model(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(agents, "BedrockModel", fake_bedrock_model)

    make_bedrock_model(
        "nova-lite",
        temperature=0.7,
    )

    assert captured["temperature"] == 0.7


def test_make_chat_agent_uses_streaming_chat_model_and_system_prompt(monkeypatch):
    fake_model = object()
    captured = {}

    def fake_make_bedrock_model(model_name, *, streaming, temperature=None):
        captured["model_name"] = model_name
        captured["streaming"] = streaming
        captured["temperature"] = temperature
        return fake_model

    def fake_agent(**kwargs):
        captured["agent_kwargs"] = kwargs
        return object()

    monkeypatch.setattr(agents, "CHAT_MODEL_NAME", "sonnet-4.6")
    monkeypatch.setattr(agents, "make_bedrock_model", fake_make_bedrock_model)
    monkeypatch.setattr(agents, "Agent", fake_agent)

    result = make_chat_agent()

    assert result is not None
    assert captured["model_name"] == "sonnet-4.6"
    assert captured["streaming"] is True
    assert captured["temperature"] is None
    assert captured["agent_kwargs"] == {
        "model": fake_model,
        "messages": None,
        "system_prompt": CHAT_SYSTEM_PROMPT,
        "callback_handler": None,
    }

def test_make_chat_agent_passes_initial_messages(monkeypatch):
    fake_model = object()
    captured = {}

    def fake_make_bedrock_model(model_name, *, streaming, temperature=None):
        return fake_model

    def fake_agent(**kwargs):
        captured["agent_kwargs"] = kwargs
        return object()

    monkeypatch.setattr(agents, "make_bedrock_model", fake_make_bedrock_model)
    monkeypatch.setattr(agents, "Agent", fake_agent)

    messages = [
        {
            "role": "user",
            "content": [{"text": "Existing profile context"}],
        }
    ]

    result = make_chat_agent(messages=messages)

    assert result is not None
    assert captured["agent_kwargs"]["messages"] is messages

def test_make_scoring_model_uses_non_streaming_scoring_model(monkeypatch):
    fake_model = object()
    captured = {}

    def fake_make_bedrock_model(model_name, *, streaming, temperature=None):
        captured["model_name"] = model_name
        captured["streaming"] = streaming
        captured["temperature"] = temperature
        return fake_model

    monkeypatch.setattr(agents, "SCORING_MODEL_NAME", "nova-2-lite")
    monkeypatch.setattr(agents, "make_bedrock_model", fake_make_bedrock_model)

    result = make_scoring_model()

    assert result is fake_model
    assert captured == {
        "model_name": "nova-2-lite",
        "streaming": False,
        "temperature": None,
    }
