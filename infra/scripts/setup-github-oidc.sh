#!/usr/bin/env bash
# Set up OIDC federation for GitHub Actions to deploy this repo to Azure.
# Idempotent: safe to re-run.
set -euo pipefail

REPO="${GITHUB_REPO:-agent-engineering-studio/mcp-osm}"
APP_NAME="${APP_NAME:-osm-mcp-github-deployer}"
SUBSCRIPTION="${AZURE_SUBSCRIPTION_ID:?AZURE_SUBSCRIPTION_ID required}"

az account set -s "$SUBSCRIPTION"

# 1. Create or get the AAD app
APP_ID=$(az ad app list --display-name "$APP_NAME" --query "[0].appId" -o tsv || true)
if [[ -z "$APP_ID" ]]; then
  APP_ID=$(az ad app create --display-name "$APP_NAME" --query appId -o tsv)
  echo "▶ Created AAD app $APP_NAME (appId=$APP_ID)"
else
  echo "▶ Reusing AAD app $APP_NAME (appId=$APP_ID)"
fi

SP_OID=$(az ad sp list --filter "appId eq '$APP_ID'" --query "[0].id" -o tsv || true)
if [[ -z "$SP_OID" ]]; then
  SP_OID=$(az ad sp create --id "$APP_ID" --query id -o tsv)
  echo "▶ Created service principal (objectId=$SP_OID)"
fi

# 2. Federated credentials for branch=main, tag=v*, environments dev/prod
for SUBJECT in \
  "repo:$REPO:ref:refs/heads/main" \
  "repo:$REPO:ref:refs/tags/v*" \
  "repo:$REPO:environment:dev" \
  "repo:$REPO:environment:prod"; do
  NAME="$(echo "$SUBJECT" | tr ':/' '-' | tr -cd '[:alnum:]-' | cut -c1-120)"
  if ! az ad app federated-credential list --id "$APP_ID" --query "[?name=='$NAME']" -o tsv | grep -q "$NAME"; then
    az ad app federated-credential create --id "$APP_ID" --parameters "$(cat <<EOF
{
  "name": "$NAME",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "$SUBJECT",
  "audiences": ["api://AzureADTokenExchange"]
}
EOF
)"
    echo "▶ Added federated credential: $SUBJECT"
  else
    echo "  (skip — federated credential already exists for $SUBJECT)"
  fi
done

# 3. Role assignment (Contributor on subscription scope; tighten to RG for production)
SCOPE="/subscriptions/$SUBSCRIPTION"
az role assignment create --assignee "$SP_OID" --role Contributor --scope "$SCOPE" -o none || true
echo "▶ Granted Contributor on $SCOPE"

TENANT=$(az account show --query tenantId -o tsv)
echo
echo "✅ Add these to your GitHub repo secrets / variables:"
echo "   AZURE_CLIENT_ID       = $APP_ID"
echo "   AZURE_TENANT_ID       = $TENANT"
echo "   AZURE_SUBSCRIPTION_ID = $SUBSCRIPTION"
