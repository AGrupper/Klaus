"""One-time TickTick OAuth bootstrap.

Run this locally to obtain the initial access_token + refresh_token pair.
After this script completes, you will not need to run it again unless you
revoke access or the refresh token expires.

Usage:
    python scripts/ticktick_oauth_bootstrap.py

Prerequisites:
    1. Register a developer app at https://developer.ticktick.com/
    2. Add the redirect URI: http://localhost:8765/callback
    3. Copy your client_id and client_secret into .env:
           TICKTICK_CLIENT_ID=...
           TICKTICK_CLIENT_SECRET=...
    4. Run this script. It opens a browser, captures the auth code,
       exchanges it for tokens, and writes config/ticktick_tokens.json.
    5. For Cloud Run, upload the tokens to Secret Manager using the
       gcloud commands printed at the end.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import sys
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import requests
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

load_dotenv(override=True)

_AUTHORIZE_URL = "https://ticktick.com/oauth/authorize"
_TOKEN_URL = "https://ticktick.com/oauth/token"
_REDIRECT_URI = "http://localhost:8765/callback"
_SCOPES = "tasks:read tasks:write"
_TOKEN_PATH = Path("./config/ticktick_tokens.json")


def _check_env() -> tuple[str, str]:
    client_id = os.getenv("TICKTICK_CLIENT_ID")
    client_secret = os.getenv("TICKTICK_CLIENT_SECRET")
    if not client_id or not client_secret:
        logger.error(
            "TICKTICK_CLIENT_ID and TICKTICK_CLIENT_SECRET must be set in .env.\n"
            "Get them from: https://developer.ticktick.com/"
        )
        sys.exit(1)
    return client_id, client_secret


def _build_auth_url(client_id: str) -> str:
    params = {
        "client_id": client_id,
        "scope": _SCOPES,
        "state": "ticktick_bootstrap",
        "redirect_uri": _REDIRECT_URI,
        "response_type": "code",
    }
    return _AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)


def _capture_auth_code() -> str:
    """Spin up a one-shot HTTP server on port 8765 and capture the auth code."""
    captured: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            if "code" in params:
                captured["code"] = params["code"][0]
                self.send_response(200)
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h2>TickTick auth complete. You can close this tab.</h2></body></html>"
                )
            else:
                error = params.get("error", ["unknown"])[0]
                self.send_response(400)
                self.end_headers()
                self.wfile.write(f"<html><body><p>Error: {error}</p></body></html>".encode())

        def log_message(self, fmt, *args):
            pass  # silence access logs

    server = HTTPServer(("localhost", 8765), Handler)
    server.timeout = 120
    server.handle_request()

    if "code" not in captured:
        logger.error("No auth code received. Did you approve access in the browser?")
        sys.exit(1)
    return captured["code"]


def _exchange_code(code: str, client_id: str, client_secret: str) -> dict:
    auth_header = "Basic " + base64.b64encode(
        f"{client_id}:{client_secret}".encode()
    ).decode()
    resp = requests.post(
        _TOKEN_URL,
        headers={"Authorization": auth_header},
        data={
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": _REDIRECT_URI,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if "access_token" not in data:
        logger.error("Unexpected token response: %s", data)
        sys.exit(1)
    return data


def _save_tokens(tokens: dict) -> None:
    _TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    out = {
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token", ""),
    }
    _TOKEN_PATH.write_text(json.dumps(out, indent=2))
    logger.info("Tokens saved to %s", _TOKEN_PATH)


def _print_inbox_project_id(access_token: str) -> None:
    """Fetch projects and print the Inbox project ID as a convenience."""
    try:
        resp = requests.get(
            "https://ticktick.com/open/v1/project",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        resp.raise_for_status()
        projects = resp.json()
        for p in projects:
            if p.get("kind") == "INBOX" or p.get("name", "").lower() in ("inbox", "???"):
                print(f"\nInbox project ID: {p['id']}")
                print("Set this in .env as: TICKTICK_PROJECT_ID=<id>  (or leave blank to use Inbox as default)")
                return
        print("\nProjects found:")
        for p in projects:
            print(f"  {p.get('id')} — {p.get('name')}")
    except Exception as exc:
        logger.warning("Could not fetch projects: %s", exc)


def _print_cloud_run_instructions(tokens: dict) -> None:
    access = tokens["access_token"]
    refresh = tokens.get("refresh_token", "")
    project_id = os.getenv("GCP_PROJECT_ID", "<YOUR_GCP_PROJECT_ID>")

    print("\n" + "="*60)
    print("CLOUD RUN SETUP — run these commands to upload tokens to GCP Secret Manager:")
    print("="*60)
    print(f"\n# Create secrets (first time only):")
    print(f"gcloud secrets create TICKTICK_ACCESS_TOKEN --project={project_id}")
    print(f"gcloud secrets create TICKTICK_REFRESH_TOKEN --project={project_id}")
    print(f"gcloud secrets create TICKTICK_CLIENT_ID --project={project_id}")
    print(f"gcloud secrets create TICKTICK_CLIENT_SECRET --project={project_id}")
    print(f"\n# Add the token values:")
    print(f'echo -n "{access}" | gcloud secrets versions add TICKTICK_ACCESS_TOKEN --data-file=- --project={project_id}')
    print(f'echo -n "{refresh}" | gcloud secrets versions add TICKTICK_REFRESH_TOKEN --data-file=- --project={project_id}')
    print(f'echo -n "$TICKTICK_CLIENT_ID" | gcloud secrets versions add TICKTICK_CLIENT_ID --data-file=- --project={project_id}')
    print(f'echo -n "$TICKTICK_CLIENT_SECRET" | gcloud secrets versions add TICKTICK_CLIENT_SECRET --data-file=- --project={project_id}')
    print("\n# Set TICKTICK_TOKEN_STORAGE=secret_manager in your Cloud Run deploy command.")
    print("="*60 + "\n")


def main() -> None:
    client_id, client_secret = _check_env()
    auth_url = _build_auth_url(client_id)

    print("\nOpening TickTick authorization in your browser...")
    print(f"If it doesn't open automatically, visit:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    print("Waiting for the OAuth redirect (timeout: 120s)...")
    code = _capture_auth_code()
    logger.info("Auth code received; exchanging for tokens...")

    token_data = _exchange_code(code, client_id, client_secret)
    _save_tokens(token_data)
    _print_inbox_project_id(token_data["access_token"])
    _print_cloud_run_instructions(token_data)

    print("\nLocal setup complete. Add to your .env:")
    print("  TICKTICK_TOKEN_STORAGE=file")
    print(f"  TICKTICK_TOKEN_PATH=./config/ticktick_tokens.json\n")


if __name__ == "__main__":
    main()
