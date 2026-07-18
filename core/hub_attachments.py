"""Transient GCS transport for hub chat attachments (images + PDFs).

Attachments are NOT persisted in conversation history — GCS only ferries the
bytes past the ~1MB Cloud Tasks body limit: the upload route stores the file,
the task payload carries the 32-hex id, and the worker downloads the bytes and
hands them to the orchestrator for that single turn. Objects live under
hub-uploads/ in the existing CHAT_LOGS_BUCKET (prefix-isolated from
chat-ingest's claude-code/), so no new deploy env var is needed. They are
scratch data; an out-of-band GCS lifecycle rule may delete them at any time
after a day.
"""
from __future__ import annotations

import logging
import os
import threading
import uuid

logger = logging.getLogger(__name__)

GCS_PREFIX = "hub-uploads/"
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENTS_PER_MESSAGE = 4

# mime → attachment kind. The kind drives which content block the orchestrator
# emits ("image" block vs Anthropic "document" block for PDFs).
ALLOWED_MIMES: dict[str, str] = {
    "image/jpeg": "image",
    "image/png": "image",
    "image/webp": "image",
    "image/gif": "image",
    "application/pdf": "pdf",
}

# Leading magic bytes per mime — a cheap content sniff so a mislabeled payload
# (e.g. an executable claiming image/jpeg) is rejected before it reaches GCS or
# the model. WEBP is RIFF????WEBP, checked specially below.
_MAGIC_BYTES: dict[str, tuple[bytes, ...]] = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    "application/pdf": (b"%PDF-",),
}

_client_lock = threading.Lock()
_bucket = None


def _get_bucket():
    """Lazily build and cache the GCS bucket handle (chat_ingest pattern)."""
    global _bucket
    if _bucket is None:
        with _client_lock:
            if _bucket is None:
                import google.cloud.storage  # lazy import — no I/O at import time

                client = google.cloud.storage.Client()
                _bucket = client.bucket(os.environ["CHAT_LOGS_BUCKET"])
    return _bucket


def _reset_client_cache_for_tests() -> None:
    global _bucket
    _bucket = None


def _sniff_ok(data: bytes, mime: str) -> bool:
    if mime == "image/webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return any(data.startswith(magic) for magic in _MAGIC_BYTES[mime])


def save_attachment(data: bytes, mime: str, filename: str) -> dict:
    """Validate and upload one attachment; return its transport metadata.

    Returns:
        {"id", "kind", "mime", "name", "size"} — the exact dict the frontend
        echoes back on send and the Cloud Tasks payload carries to the worker.

    Raises:
        ValueError: unsupported mime, oversize, empty, or magic-byte mismatch.
    """
    kind = ALLOWED_MIMES.get(mime)
    if kind is None:
        raise ValueError(f"Unsupported attachment type: {mime}")
    if not data:
        raise ValueError("Attachment is empty")
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise ValueError(
            f"Attachment too large: {len(data)} bytes "
            f"(max {MAX_ATTACHMENT_BYTES})"
        )
    if not _sniff_ok(data, mime):
        raise ValueError(f"Attachment content does not match declared type {mime}")

    att_id = uuid.uuid4().hex
    blob = _get_bucket().blob(f"{GCS_PREFIX}{att_id}")
    blob.metadata = {"filename": filename}
    blob.upload_from_string(data, content_type=mime)
    logger.info("hub attachment saved id=%s mime=%s size=%d", att_id, mime, len(data))
    return {"id": att_id, "kind": kind, "mime": mime, "name": filename, "size": len(data)}


def load_attachment(attachment_id: str) -> tuple[bytes, str, str]:
    """Download one attachment by id; return (data, mime, filename).

    Raises:
        ValueError: malformed id (must be 32 lowercase hex — path-traversal guard).
        FileNotFoundError: no such object (e.g. lifecycle-expired).
    """
    if (
        len(attachment_id) != 32
        or not all(c in "0123456789abcdef" for c in attachment_id)
    ):
        raise ValueError(f"Malformed attachment id: {attachment_id!r}")

    blob = _get_bucket().blob(f"{GCS_PREFIX}{attachment_id}")
    if not blob.exists():
        raise FileNotFoundError(f"Attachment not found: {attachment_id}")
    data = blob.download_as_bytes()
    mime = blob.content_type or "application/octet-stream"
    filename = (blob.metadata or {}).get("filename", attachment_id)
    return data, mime, filename
