"""Retry behaviour for the wttr.in weather read.

wttr.in is a free, unauthenticated service and it fails often — read timeouts and
500s several times an hour in production logs. The call sits inside
GET /api/today, so both halves matter: one retry absorbs the common transient
failure, and the timeout stays short because a ten-second hang would set the
floor for every Hub page load.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from mcp_tools.weather_tool import (
    _MAX_ATTEMPTS,
    _REQUEST_TIMEOUT_SECONDS,
    WeatherUnavailableError,
    fetch_weather,
)


_PAYLOAD = {
    "current_condition": [{
        "temp_C": "30", "FeelsLikeC": "32", "humidity": "60",
        "weatherDesc": [{"value": "Sunny"}],
    }],
    "weather": [
        {"maxtempC": "32", "mintempC": "24",
         "astronomy": [{"sunrise": "06:00 AM", "sunset": "07:30 PM"}],
         "hourly": [{}, {}, {}, {}, {"chanceofrain": "0",
                                     "weatherDesc": [{"value": "Sunny"}]}]},
        {"maxtempC": "31", "mintempC": "23",
         "hourly": [{}, {}, {}, {}, {"chanceofrain": "10",
                                     "weatherDesc": [{"value": "Clear"}]}]},
    ],
}


def _ok_response() -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = _PAYLOAD
    return resp


def test_a_transient_failure_is_retried_once():
    """The common case — one timeout, then a good response — must succeed."""
    with patch("mcp_tools.weather_tool.requests.get") as get, \
         patch("mcp_tools.weather_tool.time.sleep"):
        get.side_effect = [requests.Timeout("read timed out"), _ok_response()]
        result = fetch_weather("Tel Aviv")

    assert get.call_count == 2
    assert result["current"]["condition"] == "Sunny"
    assert result["current"]["temp_c"] == 30


def test_every_attempt_failing_raises_with_the_last_error():
    """Exhausted retries still raise WeatherUnavailableError, not the raw error."""
    with patch("mcp_tools.weather_tool.requests.get") as get, \
         patch("mcp_tools.weather_tool.time.sleep"):
        get.side_effect = requests.Timeout("read timed out")
        with pytest.raises(WeatherUnavailableError, match="wttr.in request failed"):
            fetch_weather("Tel Aviv")

    assert get.call_count == _MAX_ATTEMPTS


def test_a_success_makes_no_second_call():
    """No retry when the first attempt works — this runs on every Hub refresh."""
    with patch("mcp_tools.weather_tool.requests.get") as get:
        get.return_value = _ok_response()
        fetch_weather("Tel Aviv")

    assert get.call_count == 1


def test_non_json_is_retried_and_reported_as_unavailable():
    """wttr.in returns an HTML error page under load — treat it as a failure."""
    bad = MagicMock()
    bad.raise_for_status.return_value = None
    bad.json.side_effect = ValueError("Expecting value")

    with patch("mcp_tools.weather_tool.requests.get") as get, \
         patch("mcp_tools.weather_tool.time.sleep"):
        get.side_effect = [bad, _ok_response()]
        result = fetch_weather("Tel Aviv")

    assert get.call_count == 2
    assert result["today"]["max_c"] == 32


def test_the_timeout_cannot_dominate_a_hub_page_load():
    """Total worst case stays well under the ~3s /api/today already costs."""
    assert _REQUEST_TIMEOUT_SECONDS <= 5
    assert _REQUEST_TIMEOUT_SECONDS * _MAX_ATTEMPTS <= 10
