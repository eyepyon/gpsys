# 推論サービス（InferRun）用コンテナイメージ。
#
# Cloud Run（GPU: NVIDIA L4）で実行するFastAPIアプリケーション
# （regional_revitalization.infer_run_api:app）をuvicornでホストする。
#
# 【注記】現在の実装（`inference.MockInferenceClient`）は実際のGemma 4 12B QAT
# モデルの読み込みを行わないモック実装である。実モデルを組み込む際は、
# 本DockerfileのベースイメージをCUDA対応イメージ（例:
# `nvidia/cuda:12.x-runtime-ubuntu22.04`）に変更し、モデル重みの取得・
# 推論ライブラリ（vLLM等）のインストールを追加する必要がある。
#
# ビルドコンテキストはリポジトリルート（`docker build -f docker/infer/Dockerfile .`）を
# 想定する。

FROM python:3.11-slim AS builder

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ".[api]"

FROM python:3.11-slim

RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src ./src

USER appuser

ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn regional_revitalization.infer_run_api:app --host 0.0.0.0 --port ${PORT}"]
