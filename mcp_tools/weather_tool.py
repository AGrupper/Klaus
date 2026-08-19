"""Weather tool — current conditions and forecast via wttr.in.

Public, no auth required. Returns structured data for Tel Aviv by default.
Raises WeatherUnavailableError on network or parse failure.
"""
from __future__ import annotations

import logging
import time

import requests

logger = logging.getLogger(__name__)

# Short enough that a hung wttr.in cannot dominate GET /api/today, which fans out
# to Garmin and Google Calendar concurrently and finishes in ~3s.
_REQUEST_TIMEOUT_SECONDS = 4
_MAX_ATTEMPTS = 2
_RETRY_DELAY_SECONDS = 0.5


class WeatherUnavailableError(Exception):
    """Raised when wttr.in is unreachable or returns unexpected data."""


def fetch_weather(location: str = "Tel Aviv") -> dict:
    """Fetch current conditions and two-day forecast for a location.

    Args:
        location: City name or coordinates accepted by wttr.in. Defaults to Tel Aviv.

    Returns:
        {
            "current": {"temp_c", "feels_like_c", "condition", "humidity"},
            "today":    {"min_c", "max_c", "sunrise", "sunset", "rain_chance"},
            "tomorrow": {"min_c", "max_c", "condition", "rain_chance"},
        }

    Raises:
        WeatherUnavailableError: On HTTP error or missing data in the response.
    """
    url = f"https://wttr.in/{requests.utils.quote(location)}?format=j1"
    # wttr.in is a free service and fails often — read timeouts and 500s several
    # times an hour in production. One retry absorbs most of it; the timeout is
    # kept short because this call sits inside GET /api/today, where a ten-second
    # hang would set the floor for every Hub page load.
    last_exc: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            resp = requests.get(url, timeout=_REQUEST_TIMEOUT_SECONDS)
            resp.raise_for_status()
            data = resp.json()
            break
        except requests.RequestException as exc:
            last_exc = WeatherUnavailableError(f"wttr.in request failed: {exc}")
        except ValueError as exc:
            last_exc = WeatherUnavailableError(f"wttr.in returned non-JSON: {exc}")
        if attempt + 1 < _MAX_ATTEMPTS:
            time.sleep(_RETRY_DELAY_SECONDS)
    else:
        raise last_exc  # type: ignore[misc]

    try:
        current_cond = data["current_condition"][0]
        today_weather = data["weather"][0]
        tomorrow_weather = data["weather"][1]

        # Use the midday hourly slot (index 4 = noon) for representative rain/condition.
        today_noon = today_weather["hourly"][4]
        tomorrow_noon = tomorrow_weather["hourly"][4]

        return {
            "current": {
                "temp_c": int(current_cond["temp_C"]),
                "feels_like_c": int(current_cond["FeelsLikeC"]),
                "condition": current_cond["weatherDesc"][0]["value"],
                "humidity": int(current_cond["humidity"]),
            },
            "today": {
                "min_c": int(today_weather["mintempC"]),
                "max_c": int(today_weather["maxtempC"]),
                "sunrise": today_weather["astronomy"][0]["sunrise"],
                "sunset": today_weather["astronomy"][0]["sunset"],
                "rain_chance": int(today_noon.get("chanceofrain", 0)),
            },
            "tomorrow": {
                "min_c": int(tomorrow_weather["mintempC"]),
                "max_c": int(tomorrow_weather["maxtempC"]),
                "condition": tomorrow_noon["weatherDesc"][0]["value"],
                "rain_chance": int(tomorrow_noon.get("chanceofrain", 0)),
            },
        }
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise WeatherUnavailableError(f"Unexpected wttr.in response shape: {exc}") from exc
