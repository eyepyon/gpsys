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

RADIUS_KM = 10.0
MAX_RESULTS = 100
MIN_SEED_DISTANCE_KM = 2.0
MIN_RESULT_DISTANCE_KM = 0.05


def distance_km(a: GeoPoint, b: GeoPoint) -> float:
    lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
    dlat = lat2 - lat1
    dlon = math.radians(b.longitude - a.longitude)
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 12742.0 * math.asin(math.sqrt(value))


async def run() -> None:
    import asyncpg

    db = parse_db_connection_json(_get_required_env("DB_CONNECTION_JSON"))
    pool = await asyncpg.create_pool(**db)
    try:
        rows = await pool.fetch(
            """SELECT search_request_id,
                      ST_Y(location::geometry) latitude,
                      ST_X(location::geometry) longitude
               FROM search_requests ORDER BY created_at DESC LIMIT 500"""
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
            for place in client.search_text(point, RADIUS_KM, "閉店 店舗"):
                if place.business_status != BusinessStatus.CLOSED_PERMANENTLY:
                    continue
                if any(distance_km(place.location, saved.location) < MIN_RESULT_DISTANCE_KM for _, saved in found.values()):
                    continue
                found.setdefault(place.place_id, (request_id, place))
                if len(found) >= MAX_RESULTS:
                    break
            if len(found) >= MAX_RESULTS:
                break

        now = datetime.now(timezone.utc)
        repository = PostgresVacantPropertyRepository(pool)
        for request_id, place in found.values():
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
                    types,address,phone_number,is_registered,created_at)
                   SELECT $1,$2,$3,$4,ST_MakePoint($5,$6)::geography,$7,$8,$9,$10,true,$11
                   WHERE NOT EXISTS (SELECT 1 FROM places_search_results WHERE place_id=$3)""",
                uuid4(), request_id, place.place_id, place.name,
                place.location.longitude, place.location.latitude,
                place.business_status.value, place.types, place.address,
                place.phone_number, now,
            )
    finally:
        await pool.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
