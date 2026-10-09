FROM python:3.12-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f AS base
FROM base AS builder
WORKDIR /app
RUN pip install --no-cache-dir uv==0.12.23
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv sync --locked --extra dev --group build \
    && uv run --no-sync python -m build --wheel --no-isolation \
    && uv export --locked --no-dev --no-emit-project -o requirements.txt \
    && uv venv /opt/venv \
    && uv pip install --python /opt/venv/bin/python --require-hashes -r requirements.txt \
    && uv pip install --python /opt/venv/bin/python --no-deps dist/*.whl
FROM base
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN useradd --uid 10001 --create-home sshmcp \
    && mkdir /data && chown 10001:10001 /data && chmod 700 /data
USER 10001:10001
EXPOSE 8000
ENTRYPOINT ["ssh-mcp"]
CMD ["serve", "--config", "/config/config.json", "--database", "/data/ssh-mcp.sqlite3"]
