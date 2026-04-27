#!/usr/bin/env bash
# infra/ollama/entrypoint.sh
# Bake qwen2.5:16k from qwen2.5:7b-instruct + Modelfile on first start, then keep serving.
set -euo pipefail

ollama serve &
SERVE_PID=$!

# Wait for ollama API
for i in $(seq 1 60); do
  if ollama list >/dev/null 2>&1; then break; fi
  sleep 1
done

if ! ollama list | grep -q "qwen2.5:16k"; then
  echo "▶ Baking qwen2.5:16k from Modelfile..."
  ollama pull qwen2.5:7b-instruct
  ollama create qwen2.5:16k -f /Modelfile
fi

wait "$SERVE_PID"
