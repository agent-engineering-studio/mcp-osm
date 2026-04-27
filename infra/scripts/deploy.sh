#!/usr/bin/env bash
# infra/scripts/deploy.sh — provision RG + Bicep deployment
set -euo pipefail

ENV="${ENVIRONMENT:-dev}"
LOCATION="${AZURE_LOCATION:-westeurope}"
RG="${AZURE_RESOURCE_GROUP:-rg-osm-mcp-${ENV}}"
SUBSCRIPTION="${AZURE_SUBSCRIPTION_ID:?AZURE_SUBSCRIPTION_ID is required}"

az account set -s "$SUBSCRIPTION"
az group create -n "$RG" -l "$LOCATION" -o none

echo "▶ Deploying Bicep main.bicep to $RG..."
az deployment group create \
  -g "$RG" \
  -f infra/bicep/main.bicep \
  -p infra/bicep/main.parameters.json \
  -p environment="$ENV" \
  -p anthropicApiKey="${ANTHROPIC_API_KEY:-}" \
  -p azureAiProjectEndpoint="${AZURE_AI_PROJECT_ENDPOINT:-}" \
  -p azureAiModelDeploymentName="${AZURE_AI_MODEL_DEPLOYMENT_NAME:-}" \
  -p osmContactEmail="${OSM_CONTACT_EMAIL:-}" \
  -o table

FQDN=$(az containerapp show -g "$RG" -n osm-mcp-agent --query properties.configuration.ingress.fqdn -o tsv)
echo
echo "✅ Agent: https://$FQDN"
echo "   Health:      curl https://$FQDN/health"
echo "   MCP surface: https://$FQDN:8003/mcp"
