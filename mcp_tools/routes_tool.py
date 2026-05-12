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

import logging

logger = logging.getLogger(__name__)

_ROUTES_API_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
_FIELD_MASK = "routes.duration,routes.distanceMeters,routes.description"


def get_travel_time(
    origin: str,
    destination: str,
    departure_time_iso: str,
) -> dict | None:
    """Return estimated travel time via Google Routes API with traffic.

    Args:
        origin:               Origin address string.
        destination:          Destination address string.
        departure_time_iso:   ISO 8601 departure time (timezone-aware preferred).

    Returns:
        {"duration_minutes": int, "distance_km": float, "summary": str}
        or None on any error (so the caller can skip this event gracefully).
    """
    try:
        import google.auth
        import google.auth.transport.requests

        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        session = google.auth.transport.requests.AuthorizedSession(credentials)

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

        return {
            "duration_minutes": round(duration_seconds / 60),
            "distance_km": round(distance_meters / 1000, 1),
            "summary": summary,
        }

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
