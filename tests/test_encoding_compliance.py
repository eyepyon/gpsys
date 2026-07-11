"""ソースファイル・ドキュメントのUTF-8・LF改行統一を確認するテスト。

`src/`および`tests/`配下のすべての`.py`ファイルについて、
UTF-8でデコード可能であること、CRLF（`\r\n`）が含まれていないことを検証する。
日本語コメントの有無を厳密にチェックすることは困難なため、
本テストではUTF-8・LF改行の確認を主とする（Requirements 11.2, 11.3）。

Validates: Requirements 11.1, 11.2, 11.3
"""

from __future__ import annotations

from pathlib import Path

import pytest

# プロジェクトルート（本テストファイルの2階層上）
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 検査対象ディレクトリ
TARGET_DIRECTORIES = ["src", "tests"]


def _collect_python_files() -> list[Path]:
    """`src/`・`tests/`配下のすべての`.py`ファイルを収集する。

    `__pycache__`等のキャッシュディレクトリは対象外とする。
    """
    files: list[Path] = []
    for directory_name in TARGET_DIRECTORIES:
        directory = PROJECT_ROOT / directory_name
        if not directory.exists():
            continue
        for path in directory.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            files.append(path)
    return files


PYTHON_FILES = _collect_python_files()

# テストIDを相対パスにして、失敗時にどのファイルが対象かを分かりやすくする
PYTHON_FILE_IDS = [
    str(path.relative_to(PROJECT_ROOT)) for path in PYTHON_FILES
]


@pytest.fixture(scope="module")
def collected_python_files() -> list[Path]:
    """収集した対象ファイルのリストが空でないことを保証しつつ返す。"""
    assert PYTHON_FILES, (
        "src/またはtests/配下に.pyファイルが1件も見つかりませんでした。"
        "テスト対象パスの設定を確認してください。"
    )
    return PYTHON_FILES


def test_対象ファイルが1件以上収集される(
    collected_python_files: list[Path],
) -> None:
    """検査対象の`.py`ファイルが1件以上存在することを確認する。"""
    assert len(collected_python_files) > 0


@pytest.mark.parametrize("path", PYTHON_FILES, ids=PYTHON_FILE_IDS)
def test_ファイルがutf8でデコード可能であること(path: Path) -> None:
    """ファイルの内容がUTF-8として正しくデコードできることを確認する

    （Requirements 11.2）。
    """
    raw_bytes = path.read_bytes()
    try:
        raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        pytest.fail(f"{path}はUTF-8としてデコードできません: {exc}")


@pytest.mark.parametrize("path", PYTHON_FILES, ids=PYTHON_FILE_IDS)
def test_ファイルにcrlf改行が含まれないこと(path: Path) -> None:
    """ファイルの内容にCRLF（`\\r\\n`）改行が含まれないことを確認する

    （Requirements 11.3）。改行コードはLFに統一されていることを保証する。
    """
    raw_bytes = path.read_bytes()
    assert b"\r\n" not in raw_bytes, f"{path}にCRLF改行が含まれています"
    assert b"\r" not in raw_bytes, f"{path}にCR単独の改行が含まれています"
