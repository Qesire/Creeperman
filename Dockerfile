FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN python -m pip install --no-cache-dir ".[worker,archive]" && useradd -m -u 10001 worker && mkdir -p /app/work && chown worker /app/work
USER worker
ENTRYPOINT ["creeperman"]
