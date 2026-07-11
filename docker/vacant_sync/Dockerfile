# 居抜き物件同期サービス（VacantPropertySyncService）用コンテナイメージ。
#
# Cloud Run Jobsとして実行するバッチスクリプト
# （regional_revitalization.vacant_property_sync_job:main）を実行する。
#
# ビルドコンテキストはリポジトリルート
# （`docker build -f docker/vacant_sync/Dockerfile .`）を想定する。

FROM python:3.11-slim AS builder

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ".[postgres]" httpx>=0.27.0 google-cloud-secret-manager>=2.20.0

FROM python:3.11-slim

RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src ./src

USER appuser

CMD ["python", "-m", "regional_revitalization.vacant_property_sync_job"]
