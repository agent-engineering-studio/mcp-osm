# osm-mcp-agent/src/osm_agent/mcp_surface.py
"""Expose the running ChatAgent as a Streamable HTTP MCP server.

Uses Microsoft Agent Framework's native `agent.as_mcp_server()` capability,
which returns the low-level `mcp.server.Server`. We mount it through
`StreamableHTTPSessionManager` on a Starlette ASGI app.

Third-party MCP-aware clients (Claude Desktop, VS Code Copilot, other agents)
can mount this as a single intelligent tool and chain it after ckan-mcp-agent
to compose ckan→osm flows.
"""
from __future__ import annotations

import contextlib
import logging

import uvicorn
from agent_framework import Agent
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Mount

log = logging.getLogger("osm-agent.mcp-surface")


async def serve(
    agent: Agent,
    host: str,
    port: int,
    path: str,
    server_name: str = "OsmAgent",
) -> None:
    """Start the MCP HTTP server bound to the given agent instance.

    Runs forever (until cancelled). The function is async so callers can
    schedule it as one of multiple parallel asyncio tasks.

    Args:
        agent: The running agent_framework.Agent instance.
        host: Bind interface (e.g. "0.0.0.0").
        port: Bind port (e.g. 8003).
        path: URL path for the MCP endpoint (e.g. "/mcp").
        server_name: The "tool name" the MCP server exposes (defaults to "OsmAgent").
    """
    mcp_server = agent.as_mcp_server(server_name=server_name)
    manager = StreamableHTTPSessionManager(
        app=mcp_server, json_response=False, stateless=False,
    )

    @contextlib.asynccontextmanager
    async def _lifespan(_app):
        async with manager.run():
            yield

    asgi = Starlette(
        routes=[Mount(path, app=manager.handle_request)],
        lifespan=_lifespan,
    )

    log.info("MCP surface listening on http://%s:%s%s", host, port, path)
    config = uvicorn.Config(
        asgi, host=host, port=port,
        log_level="info", lifespan="on",
    )
    server = uvicorn.Server(config)
    await server.serve()
