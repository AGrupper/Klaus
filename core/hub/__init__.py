"""Data shaping behind the Hub's read APIs.

These modules build the payloads for `/api/today` and `/api/health/*`. They are
business logic, not HTTP: no request, no response, no routing — just "given a
date, what was true". They live here rather than in `interfaces/` so the route
handlers stay thin, and so `core/life_snapshot.py` can compose the same today
state for Claude without importing the web server backwards.
"""
