"""Pydantic Settings — env-driven configuration for osm-mcp-agent."""
from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ── LLM provider switch ──
    llm_provider: Literal["ollama", "claude", "azure_foundry"] = "ollama"

    # Ollama
    ollama_base_url: str = "http://osm-ollama:11434"
    ollama_llm_model: str = "qwen2.5:16k"
    ollama_num_ctx: int = 16384

    # Claude (Anthropic)
    anthropic_api_key: str | None = None
    claude_model: str = "claude-sonnet-4-6"

    # Azure AI Foundry
    azure_ai_project_endpoint: str | None = None
    azure_ai_model_deployment_name: str | None = None

    # ── osm-mcp upstream ──
    mcp_server_url: str = "http://osm-mcp:8080/mcp"
    mcp_server_name: str = "osm-mcp"
    mcp_approval_mode: Literal["never_require", "always_require"] = "never_require"

    # ── Agent identity ──
    agent_name: str = "OsmAgent"

    # ── REST API ──
    api_host: str = "0.0.0.0"
    api_port: int = 8002

    # ── MCP surface ──
    mcp_surface_enabled: bool = True
    mcp_surface_host: str = "0.0.0.0"
    mcp_surface_port: int = 8003
    mcp_surface_path: str = "/mcp"

    # ── Misc ──
    log_level: str = "INFO"


def get_settings() -> Settings:
    return Settings()
