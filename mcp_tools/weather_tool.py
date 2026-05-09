"""Weather tool — current conditions and forecast via wttr.in.

Public, no auth required. Returns structured data for Tel Aviv by default.
Raises WeatherUnavailableError on network or parse failure.
"""
from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)


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
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        raise WeatherUnavailableError(f"wttr.in request failed: {exc}") from exc
    except ValueError as exc:
        raise WeatherUnavailableError(f"wttr.in returned non-JSON: {exc}") from exc

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
