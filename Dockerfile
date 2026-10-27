FROM python:3.12-slim
LABEL io.modelcontextprotocol.server.name="io.github.CYAN-ECLIPSE-TECHNOLOGIES-LLC/muster"
WORKDIR /app
COPY server.py bazaar-manifest.json policy.json ./
COPY fixtures ./fixtures
RUN useradd -r appuser && mkdir -p /app/data && chown appuser /app/data
USER appuser
ENTRYPOINT ["python", "server.py"]
