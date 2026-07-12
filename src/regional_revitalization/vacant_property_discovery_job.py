"""Discover closed stores around recent, spatially diverse search locations."""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone
from uuid import uuid4

from regional_revitalization.models import GeoPoint
from regional_revitalization.postgres_vacant_property_repository import PostgresVacantPropertyRepository
from regional_revitalization.real_places_search_client import RealPlacesSearchClient
from regional_revitalization.vacant_property import BusinessStatus, VacantPropertyCandidate
from regional_revitalization.vacant_property_sync_job import get_places_api_key, parse_db_connection_json, _get_required_env

RADIUS_KM = 1.0
MAX_RESULTS = 400
MIN_SEED_DISTANCE_KM = 0.3
# embeddingバックフィルの1バッチあたりの行数と、1回のジョブ実行での上限。
# アプリ起動時（マイグレーション適用時）に全件を同期生成すると起動タイムアウトを
# 超過するため、バックフィルは本ジョブがバッチで行う（migrations/004参照）。
EMBEDDING_BACKFILL_BATCH_SIZE = 100
EMBEDDING_BACKFILL_MAX_PER_RUN = 2000


def distance_km(a: GeoPoint, b: GeoPoint) -> float:
    lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
    dlat = lat2 - lat1
    dlon = math.radians(b.longitude - a.longitude)
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 12742.0 * math.asin(math.sqrt(value))


async def backfill_embeddings(pool: object) -> int:
    """embedding未生成の店舗データにembeddingをバッチで生成・格納する。

    店舗名・業種タグ・住所の連結テキストから`google_ml.embedding(...)`で
    DB側生成する。1回の実行では最大`EMBEDDING_BACKFILL_MAX_PER_RUN`件までとし、
    残りは次回以降のジョブ実行で処理する（冪等）。

    Returns:
        バックフィルした行数。
    """
    total = 0
    while total < EMBEDDING_BACKFILL_MAX_PER_RUN:
        status = await pool.execute(  # type: ignore[attr-defined]
            """UPDATE places_search_results
               SET embedding = google_ml.embedding(
                   name || ' ' || array_to_string(types, ' ')
                        || COALESCE(' ' || address, '')
               )
               WHERE result_id IN (
                   SELECT result_id FROM places_search_results
                   WHERE embedding IS NULL LIMIT $1
               )""",
            min(EMBEDDING_BACKFILL_BATCH_SIZE, EMBEDDING_BACKFILL_MAX_PER_RUN - total),
        )
        # asyncpgのexecuteは"UPDATE <n>"形式のステータス文字列を返す。
        updated = int(status.split()[-1])
        total += updated
        if updated == 0:
            break
    return total


async def run() -> None:
    import asyncpg

    db = parse_db_connection_json(_get_required_env("DB_CONNECTION_JSON"))
    pool = await asyncpg.create_pool(**db)
    try:
        rows = await pool.fetch(
            """SELECT search_request_id,
                      ST_Y(location::geometry) latitude,
                      ST_X(location::geometry) longitude
               FROM search_requests
               WHERE processed_at IS NULL
               ORDER BY created_at ASC LIMIT 500"""
        )
        seeds: list[tuple[object, GeoPoint]] = []
        for row in rows:
            point = GeoPoint(latitude=row["latitude"], longitude=row["longitude"])
            if all(distance_km(point, existing) >= MIN_SEED_DISTANCE_KM for _, existing in seeds):
                seeds.append((row["search_request_id"], point))
            if len(seeds) >= 20:
                break

        client = RealPlacesSearchClient(get_places_api_key())
        found: dict[str, tuple[object, object]] = {}
        for request_id, point in seeds:
            for place in client.search_nearby(point, RADIUS_KM):
                found.setdefault(place.place_id, (request_id, place))
                if len(found) >= MAX_RESULTS:
                    break
            if len(found) >= MAX_RESULTS:
                break

        now = datetime.now(timezone.utc)
        repository = PostgresVacantPropertyRepository(pool)
        for request_id, place in found.values():
            is_closed = place.business_status == BusinessStatus.CLOSED_PERMANENTLY
            if is_closed:
                candidate = VacantPropertyCandidate(
                    place_id=place.place_id, name=place.name, location=place.location,
                    business_status=place.business_status, types=place.types,
                    address=place.address, phone_number=place.phone_number,
                    data_fetched_at=now, last_review_time=place.latest_review_time,
                    estimated_closure_period_start=None, estimated_closure_period_end=None,
                )
                await repository.upsert_by_place_id(candidate)
            await pool.execute(
                """INSERT INTO places_search_results
                   (result_id,search_request_id,place_id,name,location,business_status,
                    types,address,phone_number,is_registered,created_at,embedding)
                   SELECT $1,$2,$3,$4,ST_MakePoint($5,$6)::geography,$7,$8,$9,$10,$11,$12,
                          google_ml.embedding(
                              $4 || ' ' || array_to_string($8::text[], ' ')
                                 || COALESCE(' ' || $9, '')
                          )
                   WHERE NOT EXISTS (SELECT 1 FROM places_search_results WHERE place_id=$3)""",
                uuid4(), request_id, place.place_id, place.name,
                place.location.longitude, place.location.latitude,
                place.business_status.value, place.types, place.address,
                place.phone_number, is_closed, now,
            )
        if seeds:
            await pool.execute(
                "UPDATE search_requests SET processed_at=now() WHERE search_request_id=ANY($1::uuid[])",
                [request_id for request_id, _ in seeds],
            )
        await backfill_embeddings(pool)
    finally:
        await pool.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
