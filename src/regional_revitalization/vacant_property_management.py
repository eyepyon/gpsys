"""管理画面向けの居抜き物件候補管理（マップ検索・編集）ロジック。

`resource_management.py`（地域資源向け）と対をなす、居抜き物件候補
（`vacant_property_candidates`）に対するマップ範囲検索・編集操作を実装する。
"""

from __future__ import annotations

from regional_revitalization.vacant_property import (
    VacantPropertyCandidate,
    VacantPropertyRepository,
)


def search_vacant_properties_in_bounds(
    vacant_property_repository: VacantPropertyRepository,
    min_latitude: float,
    min_longitude: float,
    max_latitude: float,
    max_longitude: float,
    limit: int,
) -> list[VacantPropertyCandidate]:
    """管理画面のマップ表示用に、指定した矩形範囲内の居抜き物件候補を返す。

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

    return vacant_property_repository.search_in_bounds(
        min_latitude, min_longitude, max_latitude, max_longitude, limit
    )


def update_vacant_property_details(
    vacant_property_repository: VacantPropertyRepository,
    place_id: str,
    rent_yen: int | None,
    area_sqm: float | None,
    built_year: int | None,
    structure: str | None,
) -> None:
    """居抜き物件候補の手動編集項目（賃料・面積・築年数・構造）を更新する。

    これらの項目はGoogle Places APIからは取得できないため、管理画面での
    手動入力専用であり、フロント（利用者向け画面）には表示しない。

    Raises:
        ValueError: `rent_yen`/`area_sqm`/`built_year`が負の値の場合、
            または対象の`place_id`が存在しない場合。
    """
    if rent_yen is not None and rent_yen < 0:
        raise ValueError(f"rent_yenは0以上である必要があります: {rent_yen}")
    if area_sqm is not None and area_sqm < 0:
        raise ValueError(f"area_sqmは0以上である必要があります: {area_sqm}")
    if built_year is not None and built_year < 0:
        raise ValueError(f"built_yearは0以上である必要があります: {built_year}")

    vacant_property_repository.update_details(
        place_id, rent_yen, area_sqm, built_year, structure
    )
