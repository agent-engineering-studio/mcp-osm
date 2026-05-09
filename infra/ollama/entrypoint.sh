#!/usr/bin/env bash
# infra/ollama/entrypoint.sh
# Fallback bake: only runs if the model isn't already baked into the image.
# When using `make build-ollama`, the model is already present and this is a no-op.
set -euo pipefail

ollama serve &
SERVE_PID=$!

# Wait for ollama API
for i in $(seq 1 60); do
  if ollama list >/dev/null 2>&1; then break; fi
  sleep 1
done

if ! ollama list | grep -q "llama3.1:tools"; then
  echo "▶ Baking llama3.1:tools from Modelfile..."
  ollama pull llama3.1:8b
  ollama create llama3.1:tools -f /Modelfile
fi

wait "$SERVE_PID"
