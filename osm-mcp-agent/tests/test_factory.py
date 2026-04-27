"""Provider switch unit tests with mocked clients (no network)."""
from unittest.mock import patch

import pytest

from osm_agent.config import Settings
from osm_agent.factory import build_chat_client


def _settings(**kw) -> Settings:
    base = {"llm_provider": "ollama"}
    base.update(kw)
    return Settings(**base)


def test_ollama_provider_returns_ollama_client():
    s = _settings(llm_provider="ollama",
                  ollama_base_url="http://x:11434", ollama_llm_model="qwen2.5:7b")
    with patch("agent_framework_ollama.OllamaChatClient") as mock:
        build_chat_client(s)
    mock.assert_called_once()
    kw = mock.call_args.kwargs
    assert kw["host"] == "http://x:11434"
    assert kw["model"] == "qwen2.5:7b"


def test_claude_provider_requires_api_key():
    s = _settings(llm_provider="claude", anthropic_api_key=None)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        build_chat_client(s)


def test_claude_provider_returns_anthropic_client():
    s = _settings(llm_provider="claude", anthropic_api_key="sk-test",
                  claude_model="claude-sonnet-4-6")
    with patch("agent_framework_anthropic.AnthropicClient") as mock:
        build_chat_client(s)
    mock.assert_called_once()
    kw = mock.call_args.kwargs
    assert kw["api_key"] == "sk-test"
    assert kw["model"] == "claude-sonnet-4-6"


def test_azure_foundry_requires_endpoint_and_deployment():
    s = _settings(llm_provider="azure_foundry",
                  azure_ai_project_endpoint=None,
                  azure_ai_model_deployment_name=None)
    with pytest.raises(RuntimeError, match="AZURE_AI_PROJECT_ENDPOINT|AZURE_AI_MODEL_DEPLOYMENT_NAME"):
        build_chat_client(s)


def test_azure_foundry_returns_foundry_client():
    s = _settings(
        llm_provider="azure_foundry",
        azure_ai_project_endpoint="https://x.services.ai.azure.com/api/projects/p",
        azure_ai_model_deployment_name="gpt-4o-mini",
    )
    with patch("agent_framework_foundry.FoundryChatClient") as mock_fc, \
         patch("azure.identity.aio.DefaultAzureCredential") as mock_cred:
        build_chat_client(s)
    mock_fc.assert_called_once()
    kw = mock_fc.call_args.kwargs
    assert kw["project_endpoint"] == "https://x.services.ai.azure.com/api/projects/p"
    assert kw["model"] == "gpt-4o-mini"


def test_unsupported_provider_raises():
    # Bypass Literal validation by setting via __dict__
    s = _settings()
    object.__setattr__(s, "llm_provider", "unknown")
    with pytest.raises(RuntimeError, match="Unsupported"):
        build_chat_client(s)
