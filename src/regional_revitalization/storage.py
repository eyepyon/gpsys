"""Cloud Storage連携関連のインターフェースと実装。

`design.md`の「コンポーネント1: アプリ本体サービス (APIRun)」に定義された
`StorageClient` Protocolと、テスト用のインメモリ実装
`InMemoryStorageClient`、および`design.md`の「コンポーネント4: ファイルストレージ
(Cloud Storage)」に対応するGoogle Cloud Storage実装`GcsStorageClient`を実装する。

**Cloud Storageアクセス制御の方針（Requirements 9.1, 9.2, 9.3）**:
アップロードされたファイルは非公開バケットに格納し、利用者への提供は
有効期限付きの署名付きURLで行う（バケット自体を公開設定にはしない）。

**注意**: 本モジュールは`google-cloud-storage`パッケージ（`google.cloud.storage`）が
実行環境にインストールされていない場合でも読み込み自体が失敗しないよう、
importは`try/except ImportError`で保護し型ヒントのみに留める
（`postgres_repository.py`の`asyncpg`と同様のパターン）。
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    # 型チェック時のみ`google.cloud.storage`を参照する。実行時に未インストールでも
    # importエラーにならないようにするため、型ヒント専用の参照に留める。
    from google.cloud import storage as _storage_types

try:
    from google.cloud import storage as _gcs
except ImportError:  # pragma: no cover - テスト環境に`google-cloud-storage`が無い場合を想定
    _gcs = None

# 署名付きURLのデフォルト有効期限（設計判断として1時間を既定値とする）
DEFAULT_SIGNED_URL_EXPIRATION = timedelta(hours=1)


class StorageClient(Protocol):
    """Cloud Storage クライアント"""

    def upload(self, file_bytes: bytes, object_name: str, content_type: str) -> str:
        """アップロードしたオブジェクトの公開/署名付きURLを返す。"""
        ...


class InMemoryStorageClient:
    """テスト用のインメモリ`StorageClient`実装。

    アップロードされたバイト列とcontent_typeを内部辞書に保持し、
    `object_name`から一意に決まるダミーURLを返す。
    """

    def __init__(self) -> None:
        """内部データを初期化する。"""
        self._objects: dict[str, tuple[bytes, str]] = {}

    def upload(self, file_bytes: bytes, object_name: str, content_type: str) -> str:
        """アップロードされたバイト列を内部辞書に保存し、ダミーURLを返す。

        Args:
            file_bytes: アップロード対象のバイト列。
            object_name: オブジェクト名（バケット内のパス相当）。
            content_type: ファイルのMIMEタイプ。

        Returns:
            `object_name`から一意に決まるダミーURL。
        """
        self._objects[object_name] = (file_bytes, content_type)
        return f"https://storage.example.com/{object_name}"

    def __len__(self) -> int:
        """保持しているオブジェクトの件数を返す（テストでの副作用確認に使用）。"""
        return len(self._objects)


class GcsStorageClient:
    """Google Cloud Storageをバックエンドとする`StorageClient`実装。

    非公開バケットへファイルをアップロードし、利用者への提供は
    有効期限付きの署名付きURLで行う（Requirements 9.1, 9.2, 9.3）。
    バケット自体は非公開設定のまま運用することを前提とし、
    本クラスはバケットの公開設定変更を行わない。
    """

    def __init__(
        self,
        bucket_name: str,
        client: "_storage_types.Client | None" = None,
        signed_url_expiration: timedelta = DEFAULT_SIGNED_URL_EXPIRATION,
    ) -> None:
        """バケット名とGCSクライアントを受け取って初期化する。

        Args:
            bucket_name: アップロード先の非公開Cloud Storageバケット名。
            client: `google.cloud.storage.Client`のインスタンス。省略時は
                `google.cloud.storage.Client()`で生成する（`google-cloud-storage`が
                インストールされていない環境では省略時に呼び出すとエラーになる）。
            signed_url_expiration: 発行する署名付きURLの有効期限。
                省略時は`DEFAULT_SIGNED_URL_EXPIRATION`（1時間）を使用する。
        """
        if client is None:
            if _gcs is None:  # pragma: no cover - google-cloud-storage未インストール時
                raise RuntimeError(
                    "google-cloud-storageパッケージがインストールされていないため、"
                    "clientを明示的に指定してください。"
                )
            client = _gcs.Client()
        self._client = client
        self._bucket_name = bucket_name
        self._signed_url_expiration = signed_url_expiration

    def upload(self, file_bytes: bytes, object_name: str, content_type: str) -> str:
        """非公開バケットへファイルをアップロードし、有効期限付き署名付きURLを返す。

        Args:
            file_bytes: アップロード対象のバイト列。
            object_name: オブジェクト名（バケット内のパス相当）。
            content_type: ファイルのMIMEタイプ。

        Returns:
            アップロードされたオブジェクトに対する、有効期限付きの署名付きURL。
        """
        bucket = self._client.bucket(self._bucket_name)
        blob = bucket.blob(object_name)
        blob.upload_from_string(file_bytes, content_type=content_type)
        return blob.generate_signed_url(expiration=self._signed_url_expiration)
