# infra/ollama/Dockerfile
#
# Bakes llama3.1:tools (custom Modelfile over llama3.1:8b) into the image at
# build time, so `docker compose up` is instant — no first-run pull/polling.
# llama3.1 is used because it has reliable native function-calling support;
# small Qwen variants tend to skip tool calls and answer from memory.
FROM ollama/ollama:latest

COPY Modelfile /Modelfile
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Pre-pull the base model and apply the Modelfile so the container starts ready.
# `ollama serve` is started in the background just for this RUN step; the daemon
# is killed before the layer is committed, but /root/.ollama (model blobs) is kept.
RUN set -eux; \
    ollama serve & \
    SERVER_PID=$!; \
    for i in $(seq 1 60); do ollama list >/dev/null 2>&1 && break; sleep 1; done; \
    ollama pull llama3.1:8b; \
    ollama create llama3.1:tools -f /Modelfile; \
    kill "$SERVER_PID"; \
    wait "$SERVER_PID" 2>/dev/null || true

ENTRYPOINT ["/entrypoint.sh"]
