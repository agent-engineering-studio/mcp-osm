# osm-mcp-agent/src/osm_agent/main.py
"""Entrypoint: runs FastAPI (REST :8002) and MCP surface (:8003) in parallel
in the same process.

A single AgentSession (one upstream connection to osm-mcp) is shared between
both surfaces — created here in `_serve_both` and injected into the api module
so its lifespan handler reuses it instead of creating its own.
"""
from __future__ import annotations

import asyncio
import logging

import uvicorn

from . import api as api_module
from .api import app as fastapi_app
from .config import get_settings
from .factory import AgentSession
from .mcp_surface import serve as serve_mcp


async def _serve_both() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )
    log = logging.getLogger("osm-agent.main")

    async with AgentSession(settings) as sess:
        # Inject the shared session so the FastAPI lifespan skips its own creation.
        api_module._session = sess
        api_module._settings = settings

        config = uvicorn.Config(
            fastapi_app,
            host=settings.api_host, port=settings.api_port,
            log_level=settings.log_level.lower(),
            lifespan="on",
        )
        rest_server = uvicorn.Server(config)

        tasks: list[asyncio.Task] = [asyncio.create_task(rest_server.serve(), name="rest")]

        if settings.mcp_surface_enabled:
            async def _mcp_task() -> None:
                await serve_mcp(
                    sess.agent,
                    host=settings.mcp_surface_host,
                    port=settings.mcp_surface_port,
                    path=settings.mcp_surface_path,
                    server_name=settings.agent_name,
                )

            tasks.append(asyncio.create_task(_mcp_task(), name="mcp"))
            log.info(
                "MCP surface enabled at %s:%d%s",
                settings.mcp_surface_host,
                settings.mcp_surface_port,
                settings.mcp_surface_path,
            )
        else:
            log.info("MCP surface disabled (MCP_SURFACE_ENABLED=false)")

        log.info(
            "REST API at http://%s:%d  /health /chat /chat/stream /chat/with-geojson /compose-map",
            settings.api_host, settings.api_port,
        )
        try:
            await asyncio.gather(*tasks)
        finally:
            api_module._session = None
            api_module._settings = None


def run() -> None:
    """Console-script entrypoint. Wired to `osm-agent` in pyproject.toml."""
    asyncio.run(_serve_both())


if __name__ == "__main__":
    run()
