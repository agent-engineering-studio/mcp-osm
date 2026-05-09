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

RESPONSE FORMAT:
- Provide a clear, concise textual summary describing the place or result.
- If a place EXISTS, describe: full name, administrative location (city, region,
  country), approximate coordinates, type (city, village, district, etc.), and
  any relevant context such as population or landmarks when available.
- If a place does NOT exist or the geocoder returns zero results, clearly state
  that no results were found. Suggest spelling corrections or alternative names
  if possible. Do NOT invent data.
- Express distances in km, durations in minutes.

Map rendering: when the user asks for a map, or you receive structured GeoJSON
data (in the prompt or via a tool result), call one of:

  - render_geojson_map(geojson=<dict>, title=?, center=?, zoom=?)
  - render_multi_layer_map(layers=[{name, geojson, style?}, ...], title=?, ...)
  - compose_map_from_resources(text=?, resources=[...], title=?, ...)

The system automatically extracts coordinates from tool results and builds
GeoJSON resources for the client. Focus on writing a clear, informative summary.
"""


def build_chat_client(settings: Settings) -> Any:
    """Return an agent_framework chat client for the configured provider.

    Mirrors ckan-mcp-agent.factory.build_chat_client. Lazy imports keep
    optional providers from being required at startup.
    """
    p = settings.llm_provider
    log.info("Building chat client for provider=%s", p)

    if p == "ollama":
        from agent_framework.ollama import OllamaChatClient
        return OllamaChatClient(
            host=settings.ollama_base_url,
            model=settings.ollama_llm_model,
        )

    if p == "claude":
        if not settings.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is required when LLM_PROVIDER=claude"
            )
        from agent_framework.anthropic import AnthropicClient
        return AnthropicClient(
            api_key=settings.anthropic_api_key,
            model=settings.claude_model,
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
            client=chat_client,
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
        """Run the agent and return just the final text."""
        result = await self.run_full(query)
        return result.text or ""

    async def run_full(self, query: str):
        """Run the agent and return the full AgentResponse (with messages).

        The returned object exposes:
        - ``.text``     — concatenation of all message texts
        - ``.messages`` — list of Message objects (user, assistant, tool roles)

        Tool results are stored in Content items with
        ``type == 'mcp_server_tool_result'``.
        """
        if self._agent is None:
            raise RuntimeError("AgentSession not entered")
        return await self._agent.run(query)
