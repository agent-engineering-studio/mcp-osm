#!/usr/bin/env bash
set -euo pipefail
ENV="${ENVIRONMENT:-dev}"
RG="${AZURE_RESOURCE_GROUP:-rg-osm-mcp-${ENV}}"
read -p "Delete resource group $RG? [y/N] " confirm
[[ "$confirm" == [yY] ]] || { echo "Aborted."; exit 1; }
az group delete -n "$RG" --yes --no-wait
echo "▶ Resource group $RG deletion started (no-wait)"
