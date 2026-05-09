# osm-mcp-agent/src/osm_agent/api.py
"""FastAPI surface for the agent.

Endpoints:
  GET  /health
  POST /chat          → ChatResponse {text, resources[GEOJSON|HTML]}
  POST /chat/stream   → SSE text stream
  POST /compose-map   → deterministic map render (no LLM)
  POST /chat/with-geojson → upload GeoJSON + message

The agent returns a **text** summary describing the place / result and
**resources** with GeoJSON FeatureCollections extracted deterministically
from MCP tool results (no LLM marker parsing).
"""
from __future__ import annotations

import json
import logging
import re
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from .config import Settings, get_settings
from .contracts import ChatRequest, ChatResponse, ComposeMapRequest, PlaceDescription, Resource
from .factory import AgentSession
from .preview import build_preview_html

log = logging.getLogger("osm-agent.api")

# Legacy marker — kept only for cleaning up LLM text if it still emits it
_RESOURCES_RE = re.compile(
    r"<!--RESOURCES_JSON-->\s*(.*?)\s*<!--/RESOURCES_JSON-->", re.DOTALL
)


# ══════════════════════════════════════════════════════════════════════════
#  Deterministic tool-result extraction
# ══════════════════════════════════════════════════════════════════════════


def _extract_tool_outputs(response) -> list[tuple[str, Any]]:
    """Walk AgentResponse.messages and collect (tool_name, output) pairs
    from every ``mcp_server_tool_result`` Content item.
    """
    results: list[tuple[str, Any]] = []
    for msg in getattr(response, "messages", []):
        for content in getattr(msg, "contents", []):
            if getattr(content, "type", None) == "mcp_server_tool_result":
                tool_name = getattr(content, "tool_name", None) or ""
                output = getattr(content, "output", None)
                if output is not None:
                    results.append((tool_name, output))
    return results


def _parse_mcp_output(output: Any) -> tuple[dict | None, list[dict]]:
    """Normalise an MCP tool output into (data_dict, resource_blocks).

    Handles: plain JSON string, dict, or list-of-content-blocks.
    """
    data: dict | None = None
    resources: list[dict] = []

    if isinstance(output, str):
        try:
            data = json.loads(output)
        except (json.JSONDecodeError, TypeError):
            pass
    elif isinstance(output, dict):
        data = output
    elif isinstance(output, list):
        for item in output:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    try:
                        data = json.loads(item.get("text", ""))
                    except (json.JSONDecodeError, TypeError):
                        pass
                elif item.get("type") == "resource":
                    resources.append(item)
            elif hasattr(item, "type"):
                itype = getattr(item, "type", "")
                if itype == "text":
                    try:
                        data = json.loads(getattr(item, "text", "") or "")
                    except (json.JSONDecodeError, TypeError):
                        pass
    return data, resources


def _tool_data_to_features(tool_name: str, data: dict) -> list[dict]:
    """Convert parsed tool output data into a list of GeoJSON Features."""
    features: list[dict] = []

    def _point(lat, lon, props: dict) -> dict:
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
            "properties": {k: v for k, v in props.items() if v is not None},
        }

    if tool_name == "geocode_address":
        for r in data.get("results", []):
            if r.get("lat") is not None and r.get("lon") is not None:
                features.append(_point(r["lat"], r["lon"], {
                    "name": r.get("display_name"),
                    "type": r.get("type"),
                    "class": r.get("class"),
                    "importance": r.get("importance"),
                }))

    elif tool_name == "reverse_geocode":
        if data.get("lat") is not None and data.get("lon") is not None:
            features.append(_point(data["lat"], data["lon"], {
                "name": data.get("display_name"),
                "type": data.get("type"),
                "address": data.get("address"),
            }))

    elif tool_name in ("find_nearby_places", "search_category_in_bbox"):
        cat = data.get("category", "")
        for p in data.get("places", []):
            if p.get("lat") is not None and p.get("lon") is not None:
                features.append(_point(p["lat"], p["lon"], {
                    "name": p.get("name"),
                    "id": p.get("id"),
                    "category": p.get("category") or cat,
                    "phone": p.get("phone"),
                    "website": p.get("website"),
                    "opening_hours": p.get("opening_hours"),
                }))

    elif tool_name == "get_route":
        geom = data.get("geometry")
        if geom and not data.get("error"):
            features.append({
                "type": "Feature",
                "geometry": geom,
                "properties": {k: v for k, v in {
                    "distance_m": data.get("distance_m"),
                    "duration_s": data.get("duration_s"),
                    "profile": data.get("profile"),
                }.items() if v is not None},
            })

    elif tool_name == "find_ev_charging_stations":
        for s in data.get("stations", []):
            if s.get("lat") is not None and s.get("lon") is not None:
                features.append(_point(s["lat"], s["lon"], {
                    "name": s.get("name"),
                    "operator": s.get("operator"),
                    "capacity": s.get("capacity"),
                    "power_kw": s.get("power_kw"),
                }))

    elif tool_name == "suggest_meeting_point":
        if data.get("lat") is not None and data.get("lon") is not None and not data.get("error"):
            features.append(_point(data["lat"], data["lon"], {
                "name": data.get("display_name", "Meeting Point"),
                "max_travel_duration_s": data.get("max_travel_duration_s"),
            }))

    elif tool_name == "explore_area":
        center = data.get("center", {})
        if center.get("lat") is not None:
            features.append(_point(center["lat"], center["lon"], {
                "name": center.get("address", "Center"), "role": "center",
            }))
        for cat, places in data.get("categories", {}).items():
            for p in places:
                if p.get("lat") is not None and p.get("lon") is not None:
                    features.append(_point(p["lat"], p["lon"], {
                        "name": p.get("name"), "category": cat,
                    }))

    elif tool_name == "analyze_commute":
        for key in ("home", "work"):
            pt = data.get(key, {})
            if pt.get("lat") is not None:
                features.append(_point(pt["lat"], pt["lon"], {
                    "name": key.title(), "role": key,
                }))

    return features


def _build_resources_from_tool_outputs(
    tool_outputs: list[tuple[str, Any]],
) -> tuple[list[Resource], dict[str, Any] | None]:
    """Build GeoJSON + HTML resources from extracted tool outputs.

    Returns
    -------
    (resources, feature_collection_or_none)
    """
    all_features: list[dict] = []
    resources: list[Resource] = []
    fc: dict[str, Any] | None = None

    for tool_name, output in tool_outputs:
        data, resource_blocks = _parse_mcp_output(output)

        # Coordinate data → GeoJSON features
        if data:
            all_features.extend(_tool_data_to_features(tool_name, data))

        # HTML resources from render_* tools
        for rb in resource_blocks:
            res = rb.get("resource", {})
            if "html" in (res.get("mimeType") or ""):
                resources.append(Resource(
                    name=(res.get("uri") or "").split("/")[-1] or "map",
                    format="HTML",
                    content=res.get("text"),
                ))

    # Wrap collected features in a single FeatureCollection resource
    if all_features:
        fc = {"type": "FeatureCollection", "features": all_features}
        resources.insert(0, Resource(
            name="osm-results",
            format="GEOJSON",
            content=json.dumps(fc, ensure_ascii=False),
        ))

    return resources, fc


def _get_assistant_text(response) -> str:
    """Extract the clean assistant text from an AgentResponse.

    Walks messages in reverse to find the last assistant message, strips
    any legacy ``<!--RESOURCES_JSON-->`` markers.
    """
    for msg in reversed(getattr(response, "messages", [])):
        if getattr(msg, "role", "") == "assistant":
            text = getattr(msg, "text", "").strip()
            if text:
                return _RESOURCES_RE.sub("", text).strip()
    # Fallback: use full response text
    raw = getattr(response, "text", "") or ""
    return _RESOURCES_RE.sub("", raw).strip()


def _build_descriptions(fc: dict[str, Any] | None) -> list[PlaceDescription]:
    """Build structured PlaceDescription list from the FeatureCollection."""
    if not fc:
        return []
    descs: list[PlaceDescription] = []
    for feat in fc.get("features", []):
        props = feat.get("properties") or {}
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates")  # [lon, lat] or nested
        name = props.get("name") or props.get("display_name") or "Unknown"

        # Determine type from geometry + properties
        geom_type = geom.get("type", "")
        if geom_type == "LineString":
            ptype = "route"
        elif geom_type == "Polygon":
            ptype = "area"
        elif props.get("category"):
            ptype = "poi"
        else:
            ptype = "city" if props.get("country") else "poi"

        lat: float | None = None
        lon: float | None = None
        if coords and geom_type == "Point":
            lon, lat = coords[0], coords[1]
        elif coords and geom_type == "LineString" and coords:
            # midpoint of the route
            mid = coords[len(coords) // 2]
            lon, lat = mid[0], mid[1]

        # Collect extra details (exclude name/display_name already used)
        details: dict[str, Any] = {}
        for key in ("category", "distance_m", "duration_s", "role",
                    "osm_type", "osm_id", "address", "type"):
            if key in props:
                details[key] = props[key]

        descs.append(PlaceDescription(
            name=name,
            type=ptype,
            lat=lat,
            lon=lon,
            country=props.get("country"),
            country_code=props.get("country_code"),
            details=details,
        ))
    return descs


def _process_agent_response(response) -> ChatResponse:
    """Convert an AgentResponse into a structured ChatResponse.

    1. Extract clean assistant text (the LLM summary).
    2. Extract MCP tool results from messages.
    3. Build GeoJSON resources from coordinate data.
    4. Build structured descriptions from features.
    5. Build HTML preview snippet for chat embeds.
    6. Collect HTML resources from render_* tool results.
    """
    text = _get_assistant_text(response)
    tool_outputs = _extract_tool_outputs(response)
    resources, fc = _build_resources_from_tool_outputs(tool_outputs)
    description = _build_descriptions(fc)
    preview_html = build_preview_html(fc, text[:120]) if fc else None
    return ChatResponse(
        text=text,
        description=description,
        preview_html=preview_html,
        resources=resources,
    )


_session: AgentSession | None = None
_settings: Settings | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global _session, _settings
    # If main.py has already injected a shared session, just use it.
    if _session is not None:
        yield
        return
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
    response = await _session.run_full(req.query)
    return _process_agent_response(response)


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    """SSE text stream — yields incremental text chunks only.

    Note: resources (GeoJSON, HTML maps) are NOT included in the stream.
    Use ``POST /chat`` for the full structured response with resources.
    """
    if _session is None:
        raise HTTPException(503, "Agent session not initialised")

    async def gen() -> AsyncIterator[bytes]:
        async for chunk in _session.agent.run(req.query, stream=True):
            if chunk.text:
                payload = json.dumps({"text": chunk.text}, ensure_ascii=False)
                yield f"data: {payload}\n\n".encode("utf-8")
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
    )
    response = await _session.run_full(enriched)
    return _process_agent_response(response)
