"""Factories for the chat client and the AgentSession.

Architecture: single ChatAgent with MCP tools sourced from osm-mcp.
No regional pre-routing (unlike ckan-mcp-agent's regex router) — OSM upstreams
are global and don't have region-specific portals.
"""
from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from typing import Any

from agent_framework import Agent, MCPStreamableHTTPTool

from .config import Settings

log = logging.getLogger("osm-agent.factory")

AGENT_INSTRUCTIONS = """\
You are an OpenStreetMap-aware geographic assistant. Answer user questions about
places, addresses, routing, points of interest, and neighborhoods by calling the
available MCP tools. Prefer tools over guessing.

Distance in km, durations in minutes. Be concise.

Map rendering: when the user asks for a map, or you receive structured GeoJSON
data (in the prompt or via a tool result), call one of:

  - render_geojson_map(geojson=<dict>, title=?, center=?, zoom=?)
  - render_multi_layer_map(layers=[{name, geojson, style?}, ...], title=?, ...)
  - compose_map_from_resources(text=?, resources=[...], title=?, ...)

The map tools return a text summary AND an HTML resource block. Tell the user
the map is available — the client renders the HTML inline.

End your answer with this block (replace [] with the actual list of resources
the tools returned, empty array if no resource was produced):

<!--RESOURCES_JSON-->
[]
<!--/RESOURCES_JSON-->
"""


def build_chat_client(settings: Settings) -> Any:
    """Return an agent_framework chat client for the configured provider.

    Mirrors ckan-mcp-agent.factory.build_chat_client. Lazy imports keep
    optional providers from being required at startup.
    """
    p = settings.llm_provider
    log.info("Building chat client for provider=%s", p)

    if p == "ollama":
        from agent_framework_ollama import OllamaChatClient
        return OllamaChatClient(
            host=settings.ollama_base_url,
            model=settings.ollama_llm_model,
        )

    if p == "claude":
        if not settings.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is required when LLM_PROVIDER=claude"
            )
        from agent_framework_anthropic import AnthropicClient
        return AnthropicClient(
            api_key=settings.anthropic_api_key,
            model=settings.claude_model,
        )

    if p == "azure_foundry":
        if not settings.azure_ai_project_endpoint:
            raise RuntimeError(
                "AZURE_AI_PROJECT_ENDPOINT is required when LLM_PROVIDER=azure_foundry"
            )
        if not settings.azure_ai_model_deployment_name:
            raise RuntimeError(
                "AZURE_AI_MODEL_DEPLOYMENT_NAME is required when LLM_PROVIDER=azure_foundry"
            )
        from agent_framework_foundry import FoundryChatClient
        from azure.identity.aio import DefaultAzureCredential
        return FoundryChatClient(
            project_endpoint=settings.azure_ai_project_endpoint,
            model=settings.azure_ai_model_deployment_name,
            credential=DefaultAzureCredential(),
        )

    raise RuntimeError(f"Unsupported LLM_PROVIDER={p!r}")


class AgentSession:
    """Long-lived ChatAgent with MCP tool, safe under FastAPI lifespan.

    Usage:
        async with AgentSession(settings) as session:
            text = await session.run("ristoranti vicino al Colosseo")
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._stack = AsyncExitStack()
        self._agent: Agent | None = None

    async def __aenter__(self) -> "AgentSession":
        log.info("Connecting to MCP server at %s", self._settings.mcp_server_url)
        mcp_tool = MCPStreamableHTTPTool(
            name=self._settings.mcp_server_name,
            url=self._settings.mcp_server_url,
            description="OpenStreetMap tools: geocoding, routing, POI search, map rendering.",
            approval_mode=self._settings.mcp_approval_mode,
        )
        await self._stack.enter_async_context(mcp_tool)

        chat_client = build_chat_client(self._settings)
        default_options: dict[str, Any] = {}
        if self._settings.llm_provider == "ollama":
            default_options["num_ctx"] = self._settings.ollama_num_ctx

        agent = Agent(
            chat_client,
            instructions=AGENT_INSTRUCTIONS,
            name=self._settings.agent_name,
            tools=[mcp_tool],
            default_options=default_options or None,
        )
        await self._stack.enter_async_context(agent)
        self._agent = agent
        log.info("Agent '%s' ready", self._settings.agent_name)
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._agent = None
        await self._stack.aclose()

    @property
    def agent(self) -> Agent:
        if self._agent is None:
            raise RuntimeError("AgentSession not entered")
        return self._agent

    async def run(self, query: str) -> str:
        if self._agent is None:
            raise RuntimeError("AgentSession not entered")
        result = await self._agent.run(query)
        text = getattr(result, "text", None)
        return text if text is not None else str(result)
