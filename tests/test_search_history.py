"""検索履歴記録モジュール（search_history.py）の単体テスト。"""

from __future__ import annotations

from regional_revitalization.models import GeoPoint
from regional_revitalization.search_history import (
    InMemorySearchRequestRepository,
    record_search_request,
)
from regional_revitalization.vacant_property import BusinessStatus


class TestRecordSearchRequest:
    async def test_records_request_with_all_fields(self) -> None:
        repo = InMemorySearchRequestRepository()
        location = GeoPoint(latitude=35.68, longitude=139.76)

        request = await record_search_request(
            repo, location, 5.0, BusinessStatus.CLOSED_PERMANENTLY, ["restaurant"], 3
        )
        assert request.location == location
        assert request.result_count == 3
        assert len(repo) == 1

    async def test_list_recent_returns_newest_first(self) -> None:
        repo = InMemorySearchRequestRepository()
        location = GeoPoint(latitude=35.0, longitude=139.0)

        first = await record_search_request(
            repo, location, 1.0, None, None, 0
        )
        second = await record_search_request(
            repo, location, 2.0, None, None, 1
        )

        results = await repo.list_recent(10)
        assert results[0].search_request_id in (first.search_request_id, second.search_request_id)
        assert len(results) == 2

    async def test_get_by_id_returns_none_for_unknown(self) -> None:
        repo = InMemorySearchRequestRepository()
        from uuid import uuid4

        assert await repo.get_by_id(uuid4()) is None
