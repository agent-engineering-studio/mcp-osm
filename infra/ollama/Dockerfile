# infra/ollama/Dockerfile
FROM ollama/ollama:latest

COPY Modelfile /Modelfile
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
