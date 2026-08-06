# syntax=docker/dockerfile:1
# YouBike 智慧調度平台：前端建置 + Python 服務（api / dagster 共用同一顆 image）

# ── 1. 前端 ──────────────────────────────────────────────────────────────
FROM node:24-slim AS web
WORKDIR /w
RUN corepack enable
COPY web/package.json web/pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile || pnpm install
COPY web/ ./
RUN pnpm build

# ── 2. Python 執行環境 ───────────────────────────────────────────────────
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    YOUBIKE_DATA_DIR=/data \
    YOUBIKE_WEB_DIST=/app/web_dist \
    DAGSTER_HOME=/data/dagster \
    TZ=Asia/Taipei

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates tzdata libgomp1 \
 && rm -rf /var/lib/apt/lists/*

# 依賴層（pyproject 不變就吃快取）
COPY pyproject.toml ./
RUN uv pip install --system --no-cache -r pyproject.toml --extra pipeline

COPY api/ ./api/
COPY pipeline/ ./pipeline/
COPY ml/ ./ml/
COPY deploy/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

COPY --from=web /w/dist ./web_dist

ARG GIT_COMMIT=dev
ENV GIT_COMMIT=${GIT_COMMIT}

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=5 \
  CMD curl -fsS http://localhost:8000/api/health || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["api"]
