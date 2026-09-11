FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY ssh_mcp ./ssh_mcp
RUN pip install --no-cache-dir .

RUN mkdir -p /work

EXPOSE 8001

CMD ["python", "-m", "ssh_mcp.mcp_server", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8001", "--path", "/mcp"]
