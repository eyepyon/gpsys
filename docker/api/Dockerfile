# アプリ本体サービス（APIRun）用コンテナイメージ。
#
# Cloud Runで実行するFastAPIアプリケーション（regional_revitalization.api:app）を
# uvicornでホストする。GPUは不要。
#
# ビルドコンテキストはリポジトリルート（`docker build -f docker/api/Dockerfile .`）を
# 想定する。

FROM python:3.11-slim AS builder

WORKDIR /app

# 依存関係の解決に必要な最小限のファイルのみを先にコピーし、
# ソースコード変更時のビルドキャッシュ再利用効率を上げる。
COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ".[api,postgres,gcs]"

FROM python:3.11-slim

# 非rootユーザーで実行する（Cloud Runのセキュリティ推奨事項）。
RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src ./src
COPY migrations ./migrations
COPY data/templates ./data/templates

USER appuser

# Cloud Runは環境変数PORTでリスンポートを指定するため、それに従う。
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn regional_revitalization.api:app --host 0.0.0.0 --port ${PORT}"]
