#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Deploy osm-mcp + osm-agent to Azure Container Apps.
#
# Steps:
#   1. Ensure resource group + ACR + Container Apps environment exist
#   2. (optional) Build and push the two container images to ACR
#   3. Create/update the two Container Apps with the right env vars and
#      with osm-agent pointing at osm-mcp via internal FQDN
#
# Usage:
#   ./scripts/deploy-azure.sh                 # full: login + build + push + deploy
#   ./scripts/deploy-azure.sh --skip-build    # deploy existing images only
#   ./scripts/deploy-azure.sh --skip-login    # CI case (az login already done)
#
# Required env vars (or provided via .env at repo root):
#   AZURE_SUBSCRIPTION_ID
#   AZURE_RESOURCE_GROUP            (default: rg-osm-mcp)
#   AZURE_LOCATION                  (default: westeurope)
#   AZURE_ACR_NAME                  (required, must be globally unique)
#   AZURE_CONTAINER_APP_ENV         (default: cae-osm-mcp)
#   AZURE_MCP_APP_NAME              (default: osm-mcp)
#   AZURE_AGENT_APP_NAME            (default: osm-agent)
#   IMAGE_TAG                       (default: latest)
#   OLLAMA_BASE_URL                 (required — the URL the agent uses to reach Ollama)
#   OLLAMA_LLM_MODEL                (default: qwen2.5:7b)
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

# Load .env if present
if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a && source .env && set +a
fi

SKIP_BUILD=0
SKIP_LOGIN=0
for arg in "$@"; do
  case "$arg" in
    --skip-build) SKIP_BUILD=1 ;;
    --skip-login) SKIP_LOGIN=1 ;;
    -h|--help)
      grep -E '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  esac
done

# ── Defaults ─────────────────────────────────────────────────────────────────
: "${AZURE_RESOURCE_GROUP:=rg-osm-mcp}"
: "${AZURE_LOCATION:=westeurope}"
: "${AZURE_CONTAINER_APP_ENV:=cae-osm-mcp}"
: "${AZURE_MCP_APP_NAME:=osm-mcp}"
: "${AZURE_AGENT_APP_NAME:=osm-agent}"
: "${IMAGE_TAG:=latest}"
: "${OLLAMA_LLM_MODEL:=qwen2.5:7b}"

require() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "ERROR: required env var $name is not set" >&2
    exit 1
  fi
}

require AZURE_ACR_NAME
require OLLAMA_BASE_URL

log() { printf "\033[1;36m[deploy]\033[0m %s\n" "$*"; }

# ── 1. Azure login + subscription ────────────────────────────────────────────
if [[ "$SKIP_LOGIN" -eq 0 ]]; then
  log "Azure login"
  az login --output none
fi

if [[ -n "${AZURE_SUBSCRIPTION_ID:-}" ]]; then
  az account set --subscription "$AZURE_SUBSCRIPTION_ID"
fi

log "Installing/updating containerapp extension"
az extension add --name containerapp --upgrade --only-show-errors >/dev/null
az provider register --namespace Microsoft.App --wait >/dev/null
az provider register --namespace Microsoft.OperationalInsights --wait >/dev/null

# ── 2. Resource group + ACR + CAE ─────────────────────────────────────────────
log "Resource group: $AZURE_RESOURCE_GROUP ($AZURE_LOCATION)"
az group create -n "$AZURE_RESOURCE_GROUP" -l "$AZURE_LOCATION" --output none

log "Azure Container Registry: $AZURE_ACR_NAME"
if ! az acr show -n "$AZURE_ACR_NAME" -g "$AZURE_RESOURCE_GROUP" -o none 2>/dev/null; then
  az acr create -n "$AZURE_ACR_NAME" -g "$AZURE_RESOURCE_GROUP" \
    -l "$AZURE_LOCATION" --sku Basic --admin-enabled true --output none
fi
ACR_LOGIN_SERVER="$(az acr show -n "$AZURE_ACR_NAME" --query loginServer -o tsv)"

log "Container Apps environment: $AZURE_CONTAINER_APP_ENV"
if ! az containerapp env show -n "$AZURE_CONTAINER_APP_ENV" -g "$AZURE_RESOURCE_GROUP" -o none 2>/dev/null; then
  az containerapp env create \
    -n "$AZURE_CONTAINER_APP_ENV" \
    -g "$AZURE_RESOURCE_GROUP" \
    -l "$AZURE_LOCATION" --output none
fi

# ── 3. Build & push images ────────────────────────────────────────────────────
MCP_IMAGE="${ACR_LOGIN_SERVER}/${AZURE_MCP_APP_NAME}:${IMAGE_TAG}"
AGENT_IMAGE="${ACR_LOGIN_SERVER}/${AZURE_AGENT_APP_NAME}:${IMAGE_TAG}"

if [[ "$SKIP_BUILD" -eq 0 ]]; then
  log "ACR login (docker)"
  az acr login --name "$AZURE_ACR_NAME"

  log "Build + push MCP image: $MCP_IMAGE"
  docker build -t "$MCP_IMAGE" ./osm-mcp
  docker push "$MCP_IMAGE"

  log "Build + push Agent image: $AGENT_IMAGE"
  docker build -t "$AGENT_IMAGE" ./osm-agent
  docker push "$AGENT_IMAGE"
fi

# Pull ACR credentials for Container Apps to consume
ACR_USERNAME="$(az acr credential show -n "$AZURE_ACR_NAME" --query username -o tsv)"
ACR_PASSWORD="$(az acr credential show -n "$AZURE_ACR_NAME" --query 'passwords[0].value' -o tsv)"

# ── 4. MCP Container App (internal ingress) ──────────────────────────────────
log "Deploying MCP app: $AZURE_MCP_APP_NAME"
if az containerapp show -n "$AZURE_MCP_APP_NAME" -g "$AZURE_RESOURCE_GROUP" -o none 2>/dev/null; then
  az containerapp update \
    -n "$AZURE_MCP_APP_NAME" -g "$AZURE_RESOURCE_GROUP" \
    --image "$MCP_IMAGE" \
    --set-env-vars MCP_TRANSPORT=sse MCP_HOST=0.0.0.0 MCP_PORT=8080 \
    --output none
else
  az containerapp create \
    -n "$AZURE_MCP_APP_NAME" -g "$AZURE_RESOURCE_GROUP" \
    --environment "$AZURE_CONTAINER_APP_ENV" \
    --image "$MCP_IMAGE" \
    --target-port 8080 \
    --ingress internal \
    --min-replicas 1 --max-replicas 3 \
    --cpu 0.5 --memory 1.0Gi \
    --registry-server "$ACR_LOGIN_SERVER" \
    --registry-username "$ACR_USERNAME" \
    --registry-password "$ACR_PASSWORD" \
    --env-vars MCP_TRANSPORT=sse MCP_HOST=0.0.0.0 MCP_PORT=8080 \
    --output none
fi

MCP_INTERNAL_FQDN="$(az containerapp show -n "$AZURE_MCP_APP_NAME" -g "$AZURE_RESOURCE_GROUP" \
  --query properties.configuration.ingress.fqdn -o tsv)"
MCP_URL="http://${MCP_INTERNAL_FQDN}/sse"
log "MCP reachable at: $MCP_URL"

# ── 5. Agent Container App (external ingress) ─────────────────────────────────
log "Deploying Agent app: $AZURE_AGENT_APP_NAME"
if az containerapp show -n "$AZURE_AGENT_APP_NAME" -g "$AZURE_RESOURCE_GROUP" -o none 2>/dev/null; then
  az containerapp update \
    -n "$AZURE_AGENT_APP_NAME" -g "$AZURE_RESOURCE_GROUP" \
    --image "$AGENT_IMAGE" \
    --set-env-vars \
      OLLAMA_BASE_URL="$OLLAMA_BASE_URL" \
      OLLAMA_LLM_MODEL="$OLLAMA_LLM_MODEL" \
      MCP_SERVER_URL="$MCP_URL" \
    --output none
else
  az containerapp create \
    -n "$AZURE_AGENT_APP_NAME" -g "$AZURE_RESOURCE_GROUP" \
    --environment "$AZURE_CONTAINER_APP_ENV" \
    --image "$AGENT_IMAGE" \
    --target-port 8090 \
    --ingress external \
    --min-replicas 1 --max-replicas 5 \
    --cpu 1.0 --memory 2.0Gi \
    --registry-server "$ACR_LOGIN_SERVER" \
    --registry-username "$ACR_USERNAME" \
    --registry-password "$ACR_PASSWORD" \
    --env-vars \
      OLLAMA_BASE_URL="$OLLAMA_BASE_URL" \
      OLLAMA_LLM_MODEL="$OLLAMA_LLM_MODEL" \
      MCP_SERVER_URL="$MCP_URL" \
    --output none
fi

AGENT_FQDN="$(az containerapp show -n "$AZURE_AGENT_APP_NAME" -g "$AZURE_RESOURCE_GROUP" \
  --query properties.configuration.ingress.fqdn -o tsv)"

log "────────────────────────────────────────────────────────────────"
log "Deployment complete."
log "Agent URL : https://${AGENT_FQDN}"
log "Health    : https://${AGENT_FQDN}/health"
log "Tools     : https://${AGENT_FQDN}/tools"
log "Chat      : POST https://${AGENT_FQDN}/chat  { \"message\": \"...\" }"
log "────────────────────────────────────────────────────────────────"
