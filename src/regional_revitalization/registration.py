"""地域資源登録機能の実装。

`design.md`の「関数5: register_resource()」に基づき、
地域資源の登録処理（入力検証・ファイルアップロード・DB登録）を実装する。
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from regional_revitalization.models import GeoPoint, RegionalResource
from regional_revitalization.repository import ResourceRepository
from regional_revitalization.storage import StorageClient


def register_resource(
    resource_repository: ResourceRepository,
    storage_client: StorageClient,
    name: str,
    category: str,
    description: str,
    location: GeoPoint,
    file_bytes: bytes | None,
    content_type: str | None,
) -> RegionalResource:
    """地域資源を登録する。

    ファイルがあればCloud Storageへアップロードし、説明文のembedding生成は
    Cloud SQL側（`google_ml_integration`拡張）に委ねてINSERTする。

    事前条件を満たさない場合は`ValueError`を発生させる
    （Requirements 5.6, 5.7, 5.8）。

    Args:
        resource_repository: 登録先のリポジトリ。
        storage_client: 添付ファイルのアップロード先クライアント。
        name: 地域資源の名称。空文字列は不可。
        category: 地域資源のカテゴリ。空文字列は不可。
        description: 地域資源の説明文。空文字列は不可。
        location: 地域資源の位置情報。`GeoPoint`の`__post_init__`で
            緯度経度の範囲は既に検証されている。
        file_bytes: 添付ファイルのバイト列。添付ファイルが無い場合はNone。
        content_type: 添付ファイルのMIMEタイプ。`file_bytes`が非Noneの場合は
            非Noneであること。

    Returns:
        登録された`RegionalResource`。`embedding`はプレースホルダ（空リスト）
        のままであり、実際の値はDB側（`google_ml_integration`拡張）で生成される。

    Raises:
        ValueError: `name`/`category`/`description`のいずれかが空文字列の場合、
            または`file_bytes`が非Noneかつ`content_type`がNoneの場合。
        Exception: `storage_client.upload()`が例外を発生させた場合、その例外を
            そのまま伝播させる（`resource_repository.insert()`は呼び出さない）。
    """
    if not name:
        raise ValueError("nameは空文字列であってはなりません")
    if not category:
        raise ValueError("categoryは空文字列であってはなりません")
    if not description:
        raise ValueError("descriptionは空文字列であってはなりません")
    if file_bytes is not None and content_type is None:
        raise ValueError(
            "file_bytesが指定された場合、content_typeも指定する必要があります"
        )

    file_url: str | None = None
    if file_bytes is not None:
        object_name = f"resources/{uuid4()}"
        # アップロード失敗時は例外がそのまま伝播し、以降のinsert()は呼び出されない
        file_url = storage_client.upload(file_bytes, object_name, content_type)

    now = datetime.now()
    # embeddingフィールドはアプリ側で計算しない。
    # resource_repository.insert() が発行するINSERT文の中で
    # google_ml.embedding(description) 相当のSQL関数呼び出しにより
    # DB側でembeddingが生成され、embeddingカラムに格納される。
    resource = RegionalResource(
        resource_id=uuid4(),
        name=name,
        category=category,
        description=description,
        location=location,
        file_url=file_url,
        embedding=[],  # プレースホルダ。実際の値はDB側で生成される
        created_at=now,
        updated_at=now,
    )
    resource_repository.insert(resource)
    return resource
