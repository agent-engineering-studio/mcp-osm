#!/usr/bin/env bash
# requests/postman/test-agent-chat.sh — newman runner
set -euo pipefail
HOST="${HOST:-http://localhost:8002}"
MCP_HOST="${MCP_HOST:-http://localhost:8003}"
OSM_MCP_HOST="${OSM_MCP_HOST:-http://localhost:8080}"
COLLECTION="$(dirname "$0")/osm-mcp-agent.postman_collection.json"

echo "▶ Waiting for agent at $HOST..."
for i in $(seq 1 30); do
  if curl -fsS "$HOST/health" >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -fsS "$HOST/health" >/dev/null || { echo "Agent never became healthy"; exit 1; }

echo "▶ Running collection via newman..."
newman run "$COLLECTION" \
  --env-var "host=$HOST" \
  --env-var "mcp_host=$MCP_HOST" \
  --env-var "osm_mcp_host=$OSM_MCP_HOST" \
  --reporters cli,json \
  --reporter-json-export "$(dirname "$0")/last-run.json"
