"""管理画面向けの地域資源管理（検索・更新・削除）ロジック。

`registration.py`（`register_resource()`）と対をなす、既存の地域資源に対する
CRUD操作のうち更新・削除・マップ範囲検索を実装する。`ResourceRepository`に
新設した`update()`/`delete()`/`search_in_bounds()`を呼び出すだけの薄いラッパーで、
入力検証のみをアプリ層（本モジュール）で行う方針は既存コードのパターンに従う。
"""

from __future__ import annotations

from uuid import UUID

from regional_revitalization.models import GeoPoint, RegionalResource
from regional_revitalization.repository import ResourceRepository


def search_resources_in_bounds(
    resource_repository: ResourceRepository,
    min_latitude: float,
    min_longitude: float,
    max_latitude: float,
    max_longitude: float,
    limit: int,
) -> list[RegionalResource]:
    """管理画面のマップ表示用に、指定した矩形範囲内の地域資源を返す。

    Raises:
        ValueError: `min_latitude > max_latitude`、
            `min_longitude > max_longitude`、または`limit`が1未満の場合。
    """
    if min_latitude > max_latitude:
        raise ValueError("min_latitudeはmax_latitude以下である必要があります")
    if min_longitude > max_longitude:
        raise ValueError("min_longitudeはmax_longitude以下である必要があります")
    if limit < 1:
        raise ValueError(f"limitは1以上である必要があります: {limit}")

    return resource_repository.search_in_bounds(
        min_latitude, min_longitude, max_latitude, max_longitude, limit
    )


def update_resource(
    resource_repository: ResourceRepository,
    resource_id: UUID,
    name: str | None,
    category: str | None,
    description: str | None,
    location: GeoPoint | None,
    municipality: str | None,
) -> RegionalResource:
    """既存の地域資源を更新する。

    Args:
        resource_repository: 更新対象のリポジトリ。
        resource_id: 更新対象の一意識別子。
        name: 新しい名称。`None`の場合は変更しない。空文字列は不可。
        category: 新しいカテゴリ。`None`の場合は変更しない。空文字列は不可。
        description: 新しい説明文。`None`の場合は変更しない。空文字列は不可。
        location: 新しい位置情報。`None`の場合は変更しない。
        municipality: 新しい市町村名。`None`の場合は変更しない。

    Returns:
        更新後の`RegionalResource`（`get_by_id`で再取得したもの）。

    Raises:
        ValueError: `name`/`category`/`description`が指定されているが
            空文字列の場合、または対象の`resource_id`が存在しない場合。
    """
    if name is not None and name == "":
        raise ValueError("nameは空文字列であってはなりません")
    if category is not None and category == "":
        raise ValueError("categoryは空文字列であってはなりません")
    if description is not None and description == "":
        raise ValueError("descriptionは空文字列であってはなりません")

    existing = resource_repository.get_by_id(resource_id)
    if existing is None:
        raise ValueError(f"地域資源が見つかりません: {resource_id}")

    resource_repository.update(
        resource_id, name, category, description, location, municipality
    )

    updated = resource_repository.get_by_id(resource_id)
    assert updated is not None  # 直前にupdate()が成功しているため必ず存在する
    return updated


def delete_resource(
    resource_repository: ResourceRepository, resource_id: UUID
) -> None:
    """既存の地域資源を削除する。

    Raises:
        ValueError: 対象の`resource_id`が存在しない場合。
    """
    existing = resource_repository.get_by_id(resource_id)
    if existing is None:
        raise ValueError(f"地域資源が見つかりません: {resource_id}")
    resource_repository.delete(resource_id)
