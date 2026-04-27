# osm-mcp-agent/src/osm_agent/api.py
"""FastAPI surface for the agent.

Endpoints (this task — Tasks 9–10 add the rest):
  GET  /health
  POST /chat
  POST /chat/stream  (SSE)

Reuses the ckan-mcp-agent <!--RESOURCES_JSON--> marker pattern so the response
shape is identical and composable.
"""
from __future__ import annotations

import json
import logging
import re
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from .config import Settings, get_settings
from .contracts import ChatRequest, ChatResponse, ComposeMapRequest, Resource
from .factory import AgentSession

log = logging.getLogger("osm-agent.api")

_RESOURCES_RE = re.compile(
    r"<!--RESOURCES_JSON-->\s*(.*?)\s*<!--/RESOURCES_JSON-->", re.DOTALL
)
_RESOURCES_MARKER_PROMPT = (
    "\n\n[SYSTEM REMINDER] After your answer, you MUST append this block "
    "(replace [] with the actual resources array — empty array [] if none):\n"
    "<!--RESOURCES_JSON-->\n[]\n<!--/RESOURCES_JSON-->"
)


def _parse_resources_block(raw: str) -> tuple[str, list[Resource]]:
    """Extract the resources JSON block and return (clean_text, resources).

    Falls back to (raw, []) if the block is absent or malformed.
    """
    match = _RESOURCES_RE.search(raw)
    if not match:
        return raw, []
    try:
        items = json.loads(match.group(1))
        if isinstance(items, dict):
            for key in ("resources", "data", "items", "results"):
                if isinstance(items.get(key), list):
                    items = items[key]
                    break
        if not isinstance(items, list):
            return raw, []
        resources = [Resource(**i) for i in items]
    except Exception:
        log.warning("could not parse resources block", exc_info=True)
        return raw, []
    text = _RESOURCES_RE.sub("", raw).strip()
    return text, resources


_session: AgentSession | None = None
_settings: Settings | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global _session, _settings
    _settings = get_settings()
    log.info("Starting osm-agent with provider=%s", _settings.llm_provider)
    _session = AgentSession(_settings)
    await _session.__aenter__()
    try:
        yield
    finally:
        if _session is not None:
            await _session.__aexit__(None, None, None)
            _session = None


app = FastAPI(title="OSM Agent API", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    if _settings is None:
        return {"status": "starting"}
    return {"status": "ok", "provider": _settings.llm_provider}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    if _session is None:
        raise HTTPException(503, "Agent session not initialised")
    raw = await _session.run(req.query + _RESOURCES_MARKER_PROMPT)
    text, resources = _parse_resources_block(raw)
    return ChatResponse(text=text, resources=resources)


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    if _session is None:
        raise HTTPException(503, "Agent session not initialised")

    async def gen() -> AsyncIterator[bytes]:
        try:
            # Try the streaming API on the underlying Agent. Different
            # agent_framework versions expose this differently — fall back to
            # one-shot run() if streaming isn't available.
            stream_method = getattr(_session.agent, "run_streaming", None) \
                or getattr(_session.agent, "run_stream", None)
            if stream_method is None:
                raise AttributeError("no streaming method on Agent")
            async for update in stream_method(req.query + _RESOURCES_MARKER_PROMPT):
                payload = json.dumps({"text": str(update)}, ensure_ascii=False)
                yield f"data: {payload}\n\n".encode("utf-8")
        except AttributeError:
            text = await _session.run(req.query + _RESOURCES_MARKER_PROMPT)
            yield f"data: {json.dumps({'text': text})}\n\n".encode("utf-8")
        yield b"event: done\ndata: {}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


# ── Composition endpoint (Task 9) ─────────────────────────────────────────


def _mcp_content_to_chat_response(blocks: list[dict]) -> ChatResponse:
    """Translate osm-mcp tool result content blocks into the ChatResponse shape.

    Heuristic: text blocks become `text` (joined), resource blocks become
    Resource entries with format inferred from mimeType. Maps that ended in
    error return the error JSON in `text` and no resources.
    """
    text_parts: list[str] = []
    resources: list[Resource] = []
    for block in blocks:
        btype = block.get("type")
        if btype == "text":
            text_parts.append(block.get("text", ""))
        elif btype == "resource":
            res = block.get("resource") or {}
            mime = res.get("mimeType", "")
            fmt = "HTML" if "html" in mime else (
                mime.split("/")[-1].upper() if mime else "BIN"
            )
            resources.append(Resource(
                name=(res.get("uri") or "").split("/")[-1] or "map",
                url=res.get("uri"),
                format=fmt,
                content=res.get("text"),
            ))
    return ChatResponse(text="\n".join(text_parts).strip(), resources=resources)


def _parse_streamable_http_response(resp: "httpx.Response") -> dict:
    """Parse a streamable-HTTP MCP response.

    The server may reply as JSON (Content-Type: application/json) or as
    Server-Sent Events (Content-Type: text/event-stream) depending on whether
    the tool call streams. For a one-shot tools/call we expect a single
    SSE 'message' event whose data is the JSON-RPC envelope, OR a plain JSON
    body. Handle both.
    """
    ctype = resp.headers.get("content-type", "")
    if ctype.startswith("application/json"):
        return resp.json()
    if "text/event-stream" in ctype:
        # Parse the first SSE 'message' event's data line.
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                payload = line[5:].strip()
                if payload:
                    import json as _json
                    return _json.loads(payload)
        raise HTTPException(502, "empty SSE stream from osm-mcp")
    # Fallback: try to parse as JSON anyway
    return resp.json()


async def _mcp_streamable_call(
    base_url: str, method: str, params: dict | None = None, request_id: int = 1
) -> dict:
    """Initialize an MCP streamable-HTTP session, call one method, return result.

    The MCP streamable-HTTP transport requires:
      1. POST /mcp with method='initialize' (server returns session id in Mcp-Session-Id)
      2. POST /mcp with the same Mcp-Session-Id and method='notifications/initialized'
      3. POST /mcp with the same Mcp-Session-Id and the actual method (tools/call etc.)

    This helper performs the 3-step dance for a single tool call.
    """
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    async with httpx.AsyncClient(timeout=60) as client:
        # 1. initialize
        init = {
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "osm-mcp-agent", "version": "0.1.0"},
            },
        }
        r1 = await client.post(base_url, json=init, headers=headers)
        if r1.status_code != 200:
            raise HTTPException(502, f"osm-mcp initialize {r1.status_code}: {r1.text[:300]}")
        session_id = r1.headers.get("Mcp-Session-Id") or r1.headers.get("mcp-session-id")
        sess_headers = dict(headers)
        if session_id:
            sess_headers["Mcp-Session-Id"] = session_id

        # 2. initialized notification (no id, no response expected)
        await client.post(
            base_url,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers=sess_headers,
        )

        # 3. real call
        body = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            body["params"] = params
        r3 = await client.post(base_url, json=body, headers=sess_headers)
        if r3.status_code != 200:
            raise HTTPException(502, f"osm-mcp {method} {r3.status_code}: {r3.text[:300]}")
        return _parse_streamable_http_response(r3)


@app.post("/compose-map", response_model=ChatResponse)
async def compose_map(req: ComposeMapRequest) -> ChatResponse:
    """Deterministic ckan→osm composition. Calls osm-mcp directly via httpx
    (no LLM cost, no token usage). Accepts the ckan-mcp-agent ChatResponse
    shape and returns the same shape with an HTML resource added.
    """
    if _settings is None:
        raise HTTPException(503, "Settings not initialised")

    data = await _mcp_streamable_call(
        base_url=_settings.mcp_server_url,
        method="tools/call",
        params={
            "name": "compose_map_from_resources",
            "arguments": req.model_dump(exclude_none=True),
        },
    )
    if "error" in data:
        raise HTTPException(502, f"osm-mcp error: {data['error']}")
    blocks = (data.get("result") or {}).get("content") or []
    return _mcp_content_to_chat_response(blocks)


# ── GeoJSON upload endpoint (Task 10) ─────────────────────────────────────
_GEOJSON_MAX_INLINE = 50_000  # bytes pasted into the prompt


@app.post("/chat/with-geojson", response_model=ChatResponse)
async def chat_with_geojson(
    message: str = Form(...),
    geojson_file: UploadFile = File(...),
) -> ChatResponse:
    """Accept a multipart upload with a GeoJSON file and a message. Prepends
    the file content to the agent prompt so the LLM can call
    render_geojson_map directly with the user's data."""
    if _session is None:
        raise HTTPException(503, "Agent session not initialised")

    raw = (await geojson_file.read()).decode("utf-8", errors="replace")
    truncated = len(raw) > _GEOJSON_MAX_INLINE
    embed = raw[:_GEOJSON_MAX_INLINE]

    enriched = (
        f"USER QUERY: {message}\n\n"
        f"ATTACHED GEOJSON (file: {geojson_file.filename}"
        f"{', truncated' if truncated else ''}):\n"
        f"```geojson\n{embed}\n```\n\n"
        "If the user asks for a map, call render_geojson_map with this GeoJSON."
        + _RESOURCES_MARKER_PROMPT
    )
    text_raw = await _session.run(enriched)
    text, resources = _parse_resources_block(text_raw)
    return ChatResponse(text=text, resources=resources)
