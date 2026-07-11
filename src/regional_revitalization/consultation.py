"""相談応答機能の実装。

`design.md`の「関数4: generate_consultation_response()」に基づき、
`ConsultationRequest`の検証、`hybrid_search()`呼び出し、
`InferenceClient.generate()`呼び出しを行い、`ConsultationResponse`を返す。
"""

from __future__ import annotations

from regional_revitalization.inference import InferenceClient
from regional_revitalization.models import ConsultationRequest, ConsultationResponse
from regional_revitalization.repository import ResourceRepository, hybrid_search


def generate_consultation_response(
    resource_repository: ResourceRepository,
    inference_client: InferenceClient,
    request: ConsultationRequest,
) -> ConsultationResponse:
    """ハイブリッド検索結果をコンテキストとして推論サービスに生成を依頼する。

    事前条件を満たさない場合は`ValueError`を発生させる
    （Requirements 1.2, 1.3）。

    Args:
        resource_repository: ハイブリッド検索対象のリポジトリ。
        inference_client: 回答生成を依頼する推論サービスクライアント。
        request: 相談リクエスト。

    Returns:
        `generated_text`と`referenced_resources`を含む`ConsultationResponse`。
        `referenced_resources`は`hybrid_search`が返した結果と一致する
        （Requirements 1.4）。

    Raises:
        ValueError: `request.query_text`が空文字列の場合、または
            `request.radius_km`が0以下の場合。
        Exception: `inference_client.generate()`が例外を発生させた場合、
            その例外をそのまま伝播させる（部分的な結果を返さない、原子性）
            （Requirements 1.5）。
    """
    if not request.query_text:
        raise ValueError("query_textは空文字列であってはなりません")
    if request.radius_km <= 0:
        raise ValueError(
            f"radius_kmは正の数である必要があります: {request.radius_km}"
        )

    resources = hybrid_search(
        resource_repository,
        request.query_text,
        request.location,
        request.radius_km,
        request.top_k,
    )
    generated_text = inference_client.generate(request.query_text, resources)
    return ConsultationResponse(
        generated_text=generated_text, referenced_resources=resources
    )
