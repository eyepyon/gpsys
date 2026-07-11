"""管理画面向けの地域資源管理ロジック（resource_management.py）の単体テスト。"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

from regional_revitalization.models import GeoPoint, RegionalResource
from regional_revitalization.repository import InMemoryResourceRepository
from regional_revitalization.resource_management import (
    delete_resource,
    search_resources_in_bounds,
    update_resource,
)


def _make_resource(
    lat: float = 35.68, lng: float = 139.76, municipality: str = ""
) -> RegionalResource:
    now = datetime.now()
    return RegionalResource(
        resource_id=uuid4(),
        name="テスト資源",
        category="イベント",
        description="説明文",
        location=GeoPoint(latitude=lat, longitude=lng),
        file_url=None,
        embedding=[0.1, 0.2, 0.3],
        created_at=now,
        updated_at=now,
        municipality=municipality,
    )


class TestSearchResourcesInBounds:
    def test_returns_resources_within_bounds(self) -> None:
        inside = _make_resource(lat=35.0, lng=139.0)
        outside = _make_resource(lat=40.0, lng=145.0)
        repo = InMemoryResourceRepository([inside, outside])

        results = search_resources_in_bounds(repo, 34.0, 138.0, 36.0, 140.0, 10)
        assert results == [inside]

    def test_rejects_inverted_latitude_bounds(self) -> None:
        repo = InMemoryResourceRepository()
        with pytest.raises(ValueError, match="min_latitude"):
            search_resources_in_bounds(repo, 40.0, 138.0, 34.0, 140.0, 10)

    def test_rejects_invalid_limit(self) -> None:
        repo = InMemoryResourceRepository()
        with pytest.raises(ValueError, match="limit"):
            search_resources_in_bounds(repo, 34.0, 138.0, 36.0, 140.0, 0)


class TestUpdateResource:
    def test_updates_specified_fields_only(self) -> None:
        resource = _make_resource()
        repo = InMemoryResourceRepository([resource])

        updated = update_resource(
            repo, resource.resource_id, "新名称", None, None, None, "渋谷区"
        )
        assert updated.name == "新名称"
        assert updated.category == resource.category
        assert updated.municipality == "渋谷区"

    def test_updates_location(self) -> None:
        resource = _make_resource()
        repo = InMemoryResourceRepository([resource])
        new_location = GeoPoint(latitude=36.0, longitude=140.0)

        updated = update_resource(
            repo, resource.resource_id, None, None, None, new_location, None
        )
        assert updated.location == new_location

    def test_rejects_empty_name(self) -> None:
        resource = _make_resource()
        repo = InMemoryResourceRepository([resource])
        with pytest.raises(ValueError, match="nameは空文字列"):
            update_resource(repo, resource.resource_id, "", None, None, None, None)

    def test_raises_for_unknown_resource_id(self) -> None:
        repo = InMemoryResourceRepository()
        with pytest.raises(ValueError, match="見つかりません"):
            update_resource(repo, uuid4(), "名前", None, None, None, None)


class TestDeleteResource:
    def test_deletes_existing_resource(self) -> None:
        resource = _make_resource()
        repo = InMemoryResourceRepository([resource])
        delete_resource(repo, resource.resource_id)
        assert len(repo) == 0

    def test_raises_for_unknown_resource_id(self) -> None:
        repo = InMemoryResourceRepository()
        with pytest.raises(ValueError, match="見つかりません"):
            delete_resource(repo, uuid4())
