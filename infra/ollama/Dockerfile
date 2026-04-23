# Custom Ollama image that auto-pulls models on first start.
#
# Models to pull are controlled by the OLLAMA_MODELS env var
# (space-separated list). Default: qwen2.5:7b
#
# Build:
#   docker build -t osm-ollama ./infra/ollama
#
# Run standalone:
#   docker run -p 11434:11434 -v ollama_models:/root/.ollama osm-ollama

FROM ollama/ollama:latest

ENV OLLAMA_MODELS="qwen2.5:7b"

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 11434

ENTRYPOINT ["/entrypoint.sh"]
