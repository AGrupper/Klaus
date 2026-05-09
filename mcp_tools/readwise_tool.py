"""Readwise tool — fetch today's reading highlights.

Calls the Readwise v2 highlights API. Requires READWISE_TOKEN env var.
Returns the most recent highlights updated today, up to `limit` items.
"""
from __future__ import annotations

import logging
import os
from datetime import date, timezone, datetime

import requests

logger = logging.getLogger(__name__)


class ReadwiseAuthError(Exception):
    """Raised when READWISE_TOKEN is missing or rejected."""


class ReadwiseUnavailableError(Exception):
    """Raised on network error or unexpected API response."""


def fetch_readwise_today(limit: int = 5) -> dict:
    """Fetch highlights that were last updated today.

    Args:
        limit: Maximum number of highlights to return. Defaults to 5.

    Returns:
        {
            "highlights": [{"text", "title", "author", "source_url"}, ...],
            "date": "YYYY-MM-DD",
            "count": int,
        }

    Raises:
        ReadwiseAuthError:       If READWISE_TOKEN is missing or returns 401.
        ReadwiseUnavailableError: On other HTTP or network errors.
    """
    token = os.environ.get("READWISE_TOKEN")
    if not token:
        raise ReadwiseAuthError("READWISE_TOKEN env var is not set")

    today_str = date.today().isoformat()
    updated_after = f"{today_str}T00:00:00Z"

    try:
        resp = requests.get(
            "https://readwise.io/api/v2/highlights/",
            headers={"Authorization": f"Token {token}"},
            params={
                "updated__gt": updated_after,
                "page_size": limit,
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        raise ReadwiseUnavailableError(f"Readwise request failed: {exc}") from exc

    if resp.status_code == 401:
        raise ReadwiseAuthError("Readwise rejected the token — check READWISE_TOKEN")
    if not resp.ok:
        raise ReadwiseUnavailableError(
            f"Readwise returned HTTP {resp.status_code}: {resp.text[:200]}"
        )

    try:
        data = resp.json()
        results = data.get("results", [])
    except ValueError as exc:
        raise ReadwiseUnavailableError(f"Readwise returned non-JSON: {exc}") from exc

    highlights = [
        {
            "text": h.get("text", ""),
            "title": h.get("title") or "",
            "author": h.get("author") or "",
            "source_url": h.get("source_url") or h.get("url") or "",
        }
        for h in results[:limit]
    ]

    return {
        "highlights": highlights,
        "date": today_str,
        "count": len(highlights),
    }
