"""`GcsStorageClient`の単体テスト。

Google Cloud Storageクライアント（`google.cloud.storage.Client`相当）を
`unittest.mock.MagicMock`でモック化し、`upload()`呼び出し後に
有効期限付きの署名付きURLが返却されることを確認する。

Validates: Requirements 9.2, 9.3
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, call

from regional_revitalization.storage import DEFAULT_SIGNED_URL_EXPIRATION, GcsStorageClient


def _build_mock_client(signed_url: str = "https://storage.googleapis.com/signed-url") -> tuple[MagicMock, MagicMock, MagicMock]:
    """モック化した`google.cloud.storage.Client`とその配下のbucket/blobを構築する。

    Returns:
        `(client, bucket, blob)`のタプル。`client.bucket(...)`が`bucket`を返し、
        `bucket.blob(...)`が`blob`を返すよう配線されている。
    """
    mock_client = MagicMock()
    mock_bucket = MagicMock()
    mock_blob = MagicMock()

    mock_client.bucket.return_value = mock_bucket
    mock_bucket.blob.return_value = mock_blob
    mock_blob.generate_signed_url.return_value = signed_url

    return mock_client, mock_bucket, mock_blob


class TestGcsStorageClientUpload:
    """`GcsStorageClient.upload()`の単体テスト。"""

    def test_uploadは署名付きURLを返す(self) -> None:
        """`upload()`呼び出し後、モックの`generate_signed_url`が返した

        署名付きURLがそのまま返却されることを確認する。
        """
        expected_url = "https://storage.googleapis.com/my-bucket/objects/sample.png?signature=abc"
        mock_client, _, _ = _build_mock_client(signed_url=expected_url)
        storage_client = GcsStorageClient(bucket_name="my-bucket", client=mock_client)

        result = storage_client.upload(
            file_bytes=b"dummy-bytes", object_name="objects/sample.png", content_type="image/png"
        )

        assert result == expected_url

    def test_uploadは対象バケットとオブジェクトを正しく参照する(self) -> None:
        """`upload()`が`client.bucket(bucket_name)`と`bucket.blob(object_name)`を

        正しい引数で呼び出すことを確認する（非公開バケットへの格納を確認）。
        """
        mock_client, mock_bucket, mock_blob = _build_mock_client()
        storage_client = GcsStorageClient(bucket_name="private-bucket", client=mock_client)

        storage_client.upload(
            file_bytes=b"dummy-bytes", object_name="objects/sample.pdf", content_type="application/pdf"
        )

        mock_client.bucket.assert_called_once_with("private-bucket")
        mock_bucket.blob.assert_called_once_with("objects/sample.pdf")
        mock_blob.upload_from_string.assert_called_once_with(
            b"dummy-bytes", content_type="application/pdf"
        )

    def test_uploadは有効期限を指定して署名付きURLを発行する(self) -> None:
        """`upload()`が`generate_signed_url(expiration=...)`を、

        コンストラクタで指定した有効期限を用いて呼び出すことを確認する
        （Requirements 9.2: 有効期限付き署名付きURLの発行）。
        """
        custom_expiration = timedelta(minutes=30)
        mock_client, _, mock_blob = _build_mock_client()
        storage_client = GcsStorageClient(
            bucket_name="my-bucket", client=mock_client, signed_url_expiration=custom_expiration
        )

        storage_client.upload(
            file_bytes=b"dummy-bytes", object_name="objects/sample.png", content_type="image/png"
        )

        mock_blob.generate_signed_url.assert_called_once_with(expiration=custom_expiration)

    def test_デフォルトの有効期限は1時間である(self) -> None:
        """有効期限を指定しない場合、既定値`DEFAULT_SIGNED_URL_EXPIRATION`（1時間）が

        `generate_signed_url()`に渡されることを確認する。
        """
        mock_client, _, mock_blob = _build_mock_client()
        storage_client = GcsStorageClient(bucket_name="my-bucket", client=mock_client)

        assert DEFAULT_SIGNED_URL_EXPIRATION == timedelta(hours=1)

        storage_client.upload(
            file_bytes=b"dummy-bytes", object_name="objects/sample.png", content_type="image/png"
        )

        mock_blob.generate_signed_url.assert_called_once_with(
            expiration=DEFAULT_SIGNED_URL_EXPIRATION
        )

    def test_uploadはアップロード後に署名付きURLを発行する呼び出し順序を守る(self) -> None:
        """`upload_from_string()`（アップロード）が`generate_signed_url()`

        （署名付きURL発行）より先に呼び出されることを確認する。
        """
        mock_client, _, mock_blob = _build_mock_client()
        manager = MagicMock()
        manager.attach_mock(mock_blob.upload_from_string, "upload_from_string")
        manager.attach_mock(mock_blob.generate_signed_url, "generate_signed_url")
        storage_client = GcsStorageClient(bucket_name="my-bucket", client=mock_client)

        storage_client.upload(
            file_bytes=b"dummy-bytes", object_name="objects/sample.png", content_type="image/png"
        )

        expected_calls = [
            call.upload_from_string(b"dummy-bytes", content_type="image/png"),
            call.generate_signed_url(expiration=DEFAULT_SIGNED_URL_EXPIRATION),
        ]
        assert manager.mock_calls == expected_calls
