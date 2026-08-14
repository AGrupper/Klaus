"""Google Routes API wrapper — traffic-aware travel time estimation.

Uses Application Default Credentials (ADC) — no separate API key is needed
when running on Cloud Run with the runtime service account.

Requires `routes.googleapis.com` to be enabled on the GCP project.

Local smoke test:
  python -m mcp_tools.routes_tool --origin "Tel Aviv" \
    --dest "Dizengoff Center, Tel Aviv" \
    --depart "2026-05-13T14:00:00+03:00"
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading

logger = logging.getLogger(__name__)

_ROUTES_API_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
_FIELD_MASK = "routes.duration,routes.distanceMeters,routes.description"
_DAILY_COMPUTATION_LIMIT = 25
_ROLLING_MINUTE_LIMIT = 5
_usage_store = None
_usage_store_lock = threading.Lock()


def _get_usage_store():
    """Return the process-wide persisted Routes ledger/cache."""
    global _usage_store
    if _usage_store is None:
        with _usage_store_lock:
            if _usage_store is None:
                from memory.firestore_db import RoutesUsageStore

                _usage_store = RoutesUsageStore(
                    os.environ.get("GCP_PROJECT_ID", "klaus-agent"),
                    os.environ.get("FIRESTORE_DATABASE", "klaus-firestore"),
                )
    return _usage_store


def _get_authorized_session():
    """Build one authenticated transport for a reserved Routes request."""
    import google.auth
    import google.auth.transport.requests

    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    return google.auth.transport.requests.AuthorizedSession(credentials)


def _fallback_event_id(origin: str, destination: str) -> str:
    """Return a stable cache identity for non-calendar/CLI callers."""
    material = f"{origin}\n{destination}".encode("utf-8")
    return f"route-{hashlib.sha256(material).hexdigest()[:24]}"


def get_travel_time(
    origin: str,
    destination: str,
    departure_time_iso: str,
    *,
    user_id: str | int | None = None,
    event_id: str | None = None,
) -> dict | None:
    """Return estimated travel time via Google Routes API with traffic.

    Args:
        origin:               Origin address string.
        destination:          Destination address string.
        departure_time_iso:   ISO 8601 departure time (timezone-aware preferred).
        user_id:              Canonical Klaus user; defaults to KLAUS_USER_ID.
        event_id:             Calendar identity for persisted cache isolation.

    Returns:
        {"duration_minutes": int, "distance_km": float, "summary": str}
        or None on any error (so the caller can skip this event gracefully).
    """
    try:
        canonical_user = str(user_id or os.environ.get("KLAUS_USER_ID", "")).strip()
        if not canonical_user:
            logger.warning("Routes omitted: KLAUS_USER_ID is not configured")
            return None
        cache_event_id = str(event_id or _fallback_event_id(origin, destination))
        usage_store = _get_usage_store()
        cached = usage_store.get_cached(
            canonical_user,
            event_id=cache_event_id,
            departure_time_iso=departure_time_iso,
        )
        if cached is not None:
            return cached
        if not usage_store.reserve(
            canonical_user,
            daily_limit=_DAILY_COMPUTATION_LIMIT,
            minute_limit=_ROLLING_MINUTE_LIMIT,
        ):
            logger.info("Routes omitted: application quota reached")
            return None

        session = _get_authorized_session()

        body = {
            "origin": {"address": origin},
            "destination": {"address": destination},
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE",
            "departureTime": _normalise_departure_time(departure_time_iso),
            "computeAlternativeRoutes": False,
            "languageCode": "en-US",
            "units": "METRIC",
        }

        response = session.post(
            _ROUTES_API_URL,
            json=body,
            headers={"X-Goog-FieldMask": _FIELD_MASK},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        routes = data.get("routes") or []
        if not routes:
            logger.warning(
                "Routes API: no routes returned for %s → %s", origin, destination
            )
            return None

        route = routes[0]
        # duration arrives as a protobuf Duration string e.g. "720s"
        duration_str: str = route.get("duration", "0s")
        duration_seconds = int(duration_str.rstrip("s"))
        distance_meters = int(route.get("distanceMeters", 0))
        summary = route.get("description", "")

        result = {
            "duration_minutes": round(duration_seconds / 60),
            "distance_km": round(distance_meters / 1000, 1),
            "summary": summary,
        }
        try:
            usage_store.put_cached(
                canonical_user,
                event_id=cache_event_id,
                departure_time_iso=departure_time_iso,
                result=result,
            )
        except Exception:
            # The quota reservation already bounded spend. A cache write
            # outage must not discard a valid estimate from this request.
            logger.warning("Routes cache write failed", exc_info=True)
        return result

    except Exception:
        logger.warning(
            "Routes API call failed for %s → %s", origin, destination, exc_info=True
        )
        return None


def _normalise_departure_time(iso_str: str) -> str:
    """Ensure the departure time is a valid RFC 3339 string for the Routes API."""
    from datetime import datetime, timezone

    try:
        dt = datetime.fromisoformat(iso_str)
        # Routes API wants a timezone-aware RFC 3339 string.
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except ValueError:
        return iso_str


# ------------------------------------------------------------------ #
# CLI smoke test                                                     #
# ------------------------------------------------------------------ #

def _cli() -> None:
    import argparse
    from dotenv import load_dotenv
    import logging as _logging

    load_dotenv(override=True)
    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Routes tool smoke test")
    parser.add_argument("--origin", required=True, help="Origin address")
    parser.add_argument("--dest", required=True, help="Destination address")
    parser.add_argument("--depart", required=True, help="Departure time (ISO 8601)")
    args = parser.parse_args()

    result = get_travel_time(args.origin, args.dest, args.depart)
    if result:
        print(f"Duration : {result['duration_minutes']} min")
        print(f"Distance : {result['distance_km']} km")
        print(f"Route    : {result['summary']}")
    else:
        print("Failed to get travel time — check logs above.")


if __name__ == "__main__":
    _cli()
