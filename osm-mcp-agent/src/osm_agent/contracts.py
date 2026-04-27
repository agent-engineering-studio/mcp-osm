"""Stable JSON-shape contracts for inter-agent composition.

These mirror the shape emitted by ckan-mcp-agent (see ckan_agent.api.Resource /
ChatResponse). The contract is the JSON shape, not the Python class — we don't
share a library with ckan-mcp-agent on purpose so each agent can evolve fields
independently.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class Resource(BaseModel):
    """A resource produced by an agent. Mirrors ckan-mcp-agent.api.Resource."""

    name: str
    url: str | None = None
    format: str
    content: str | None = None


class ChatResponse(BaseModel):
    """Universal agent reply: narrative text + heterogeneous resources."""

    text: str
    resources: list[Resource] = Field(default_factory=list)


class ChatRequest(BaseModel):
    """Body of POST /chat and POST /chat/stream."""

    query: str


class ComposeMapRequest(BaseModel):
    """Body of POST /compose-map. Accepts the same shape as ChatResponse plus
    optional rendering hints."""

    text: str = ""
    resources: list[Resource]
    title: str | None = None
    center: list[float] | None = None  # [lat, lon]
    zoom: int | None = None
