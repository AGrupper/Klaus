"""Gmail MCP tool.

Exposes Gmail operations to the Klaus agent: list unread messages, fetch full
message bodies, and mark messages as read. Authenticates lazily via the shared
`GoogleAuthManager` from `core.auth_google`.
"""
from __future__ import annotations

import base64
import logging
from typing import Any

from googleapiclient.errors import HttpError

from core.auth_google import GoogleAuthManager

logger = logging.getLogger(__name__)


class GmailTool:
    """Authenticated wrapper around the Gmail v1 REST API.

    All public methods return structured dicts so the agent can consume them
    without catching exceptions. On API failure, methods log the error and
    return a safe empty/error structure rather than raising.
    """

    def __init__(self, auth_manager: GoogleAuthManager) -> None:
        """Store the auth manager; defer service construction to first use.

        Args:
            auth_manager: A `GoogleAuthManager` instance. Its `gmail_service()`
                method will be called lazily on the first API call, not here,
                so that constructing a `GmailTool` never triggers network I/O.
        """
        self._auth_manager = auth_manager
        # Lazily populated by _get_service(); None until first use.
        self._service: Any | None = None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_service(self) -> Any:
        """Return the Gmail API service resource, building it on first call.

        Returns:
            An authenticated `googleapiclient.discovery.Resource` for Gmail v1.
        """
        if self._service is None:
            # Build the service once and cache it for the lifetime of this
            # object. Repeated calls to gmail_service() would each perform an
            # OAuth token refresh check, so caching avoids that overhead.
            self._service = self._auth_manager.gmail_service()
        return self._service

    @staticmethod
    def _headers_to_dict(headers: list[dict]) -> dict[str, str]:
        """Convert the Gmail API's header list into a plain name→value dict.

        The API returns headers as a list of {"name": str, "value": str} objects.
        Flattening them makes downstream access simpler and more readable.

        Args:
            headers: The `payload.headers` list from a Gmail message resource.

        Returns:
            A dict mapping header name to header value. Duplicate header names
            keep only the last value (sufficient for From/Subject/Date).
        """
        return {h["name"]: h["value"] for h in headers}

    @staticmethod
    def _decode_body_data(data: str) -> str:
        """Decode a base64url-encoded Gmail message body part.

        Gmail encodes body data with URL-safe base64 (RFC 4648 §5). The
        `base64.urlsafe_b64decode` call requires correct padding, which Gmail
        sometimes omits, so we re-pad before decoding.

        Args:
            data: The raw base64url string from `body.data`.

        Returns:
            The decoded text content as a UTF-8 string. Non-UTF-8 bytes are
            replaced with the replacement character rather than raising.
        """
        # Gmail strips `=` padding; add it back to satisfy the decoder.
        padded = data + "=" * (4 - len(data) % 4)
        raw_bytes = base64.urlsafe_b64decode(padded)
        return raw_bytes.decode("utf-8", errors="replace")

    @staticmethod
    def _extract_body(payload: dict) -> str:
        """Recursively walk a message payload to find the best readable body.

        Preference order: `text/plain` > `text/html`. We don't strip HTML tags
        because the agent can reason over raw HTML when plain text is absent.

        Args:
            payload: The top-level `payload` dict from a Gmail message resource.

        Returns:
            The decoded body string, or an empty string if nothing decodable is
            found.
        """
        # Helper that recurses into multipart/* parts.
        def _walk(parts: list[dict], preferred_mime: str) -> str | None:
            for part in parts:
                mime = part.get("mimeType", "")
                if mime == preferred_mime:
                    data = part.get("body", {}).get("data", "")
                    if data:
                        return GmailTool._decode_body_data(data)
                # Recurse into nested multipart containers (e.g. multipart/mixed
                # that wraps a multipart/alternative).
                if mime.startswith("multipart/"):
                    result = _walk(part.get("parts", []), preferred_mime)
                    if result:
                        return result
            return None

        parts = payload.get("parts")

        if parts:
            # Two-pass: prefer plain text, fall back to HTML.
            for mime_type in ("text/plain", "text/html"):
                body = _walk(parts, mime_type)
                if body:
                    return body
        else:
            # Simple (non-multipart) message — body lives directly on payload.
            data = payload.get("body", {}).get("data", "")
            if data:
                return GmailTool._decode_body_data(data)

        return ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_unread(self, max_results: int = 10) -> list[dict]:
        """Return metadata for the most recent unread messages.

        Performs two API calls per message: one to list IDs, then one per
        message to fetch metadata headers (From, Subject, Date). This is more
        efficient than fetching full bodies when the agent only needs to triage.

        Args:
            max_results: Maximum number of unread messages to return (default 10).

        Returns:
            A list of dicts, each containing:
                - "id"      (str): Gmail message ID.
                - "from"    (str): Sender address/name from the From header.
                - "subject" (str): Message subject.
                - "snippet" (str): Gmail's auto-generated short preview of the body.
                - "received"(str): Raw value of the Date header.
            Returns an empty list on API error or when the inbox has no unread mail.
        """
        service = self._get_service()

        try:
            # Query with `is:unread` to scope results to the unread label.
            # `userId="me"` is the canonical way to refer to the authenticated
            # user without hard-coding an email address.
            response = (
                service.users()
                .messages()
                .list(userId="me", q="is:unread", maxResults=max_results)
                .execute()
            )
        except HttpError as exc:
            logger.error("Gmail list_unread failed during messages.list: %s", exc)
            return []

        messages_stubs = response.get("messages", [])
        if not messages_stubs:
            return []

        results: list[dict] = []

        for stub in messages_stubs:
            msg_id = stub["id"]
            try:
                # Fetch only the headers we care about to minimise payload size.
                # `format="metadata"` skips the full body, which can be large.
                msg = (
                    service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=msg_id,
                        format="metadata",
                        metadataHeaders=["From", "Subject", "Date"],
                    )
                    .execute()
                )
            except HttpError as exc:
                logger.error(
                    "Gmail list_unread failed during messages.get for id=%s: %s",
                    msg_id,
                    exc,
                )
                # Skip this message but continue processing the rest.
                continue

            headers = self._headers_to_dict(msg.get("payload", {}).get("headers", []))

            results.append(
                {
                    "id": msg_id,
                    "from": headers.get("From", ""),
                    "subject": headers.get("Subject", ""),
                    # `snippet` is a top-level field on the message resource,
                    # not buried inside payload — it is Gmail's own short preview.
                    "snippet": msg.get("snippet", ""),
                    "received": headers.get("Date", ""),
                }
            )

        return results

    def get_message(self, message_id: str) -> dict:
        """Fetch a full message including decoded body by Gmail message ID.

        Args:
            message_id: The Gmail message ID (e.g. from `list_unread`).

        Returns:
            A dict containing:
                - "id"      (str): Gmail message ID.
                - "from"    (str): Sender address/name.
                - "subject" (str): Message subject.
                - "date"    (str): Raw Date header value.
                - "body"    (str): Decoded plain-text (or HTML) body content.
            On error: {"error": str, "id": message_id}.
        """
        service = self._get_service()

        try:
            # `format="full"` returns headers, body, and all MIME parts.
            # This is the heaviest format but required to decode the body.
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )
        except HttpError as exc:
            logger.error(
                "Gmail get_message failed for id=%s: %s", message_id, exc
            )
            return {"error": str(exc), "id": message_id}

        payload = msg.get("payload", {})
        headers = self._headers_to_dict(payload.get("headers", []))
        body = self._extract_body(payload)

        return {
            "id": message_id,
            "from": headers.get("From", ""),
            "subject": headers.get("Subject", ""),
            "date": headers.get("Date", ""),
            "body": body,
        }

    def mark_read(self, message_id: str) -> dict:
        """Remove the UNREAD label from a message, marking it as read.

        Args:
            message_id: The Gmail message ID to mark as read.

        Returns:
            {"id": message_id, "marked_read": True} on success.
            {"error": str, "id": message_id, "marked_read": False} on failure.
        """
        service = self._get_service()

        try:
            # `messages.modify` with `removeLabelIds` is the correct way to
            # clear the UNREAD system label. Deleting or archiving the message
            # is a destructive side-effect we deliberately avoid here.
            service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"removeLabelIds": ["UNREAD"]},
            ).execute()
        except HttpError as exc:
            logger.error(
                "Gmail mark_read failed for id=%s: %s", message_id, exc
            )
            return {"error": str(exc), "id": message_id, "marked_read": False}

        return {"id": message_id, "marked_read": True}
