FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --uid 10001 --create-home sshmcp \
    && mkdir /data && chown 10001:10001 /data && chmod 700 /data
USER 10001:10001
EXPOSE 8000
ENTRYPOINT ["ssh-mcp"]
CMD ["serve", "--config", "/config/config.json", "--database", "/data/ssh-mcp.sqlite3"]
