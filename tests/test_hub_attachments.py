"""Tests for core/hub_attachments.py — transient GCS transport for hub uploads.

Attachments are TRANSIENT (user decision, hub attachments feature): GCS is used
only to ferry bytes past the ~1MB Cloud Tasks body limit — nothing is persisted
in conversation history. Objects live under hub-uploads/{uuid4.hex} in the
existing CHAT_LOGS_BUCKET (prefix-isolated from chat-ingest's claude-code/).

The storage client is mocked at the module's _get_bucket() boundary — the same
lazy-import approach as core/chat_ingest.py.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from core import hub_attachments as ha


# Minimal valid magic-byte payloads per supported type.
_JPEG = b"\xff\xd8\xff\xe0" + b"j" * 32
_PNG = b"\x89PNG\r\n\x1a\n" + b"p" * 32
_GIF = b"GIF89a" + b"g" * 32
_WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"w" * 32
_PDF = b"%PDF-1.7\n" + b"d" * 32


def _mock_bucket():
    bucket = MagicMock(name="bucket")
    return bucket


# ------------------------------------------------------------------ #
# save_attachment                                                    #
# ------------------------------------------------------------------ #

def test_save_attachment_uploads_and_returns_metadata():
    bucket = _mock_bucket()
    with patch.object(ha, "_get_bucket", return_value=bucket):
        meta = ha.save_attachment(_JPEG, "image/jpeg", "photo.jpg")

    assert set(meta) == {"id", "kind", "mime", "name", "size"}
    assert meta["kind"] == "image"
    assert meta["mime"] == "image/jpeg"
    assert meta["name"] == "photo.jpg"
    assert meta["size"] == len(_JPEG)
    # id is a uuid4 hex — 32 lowercase hex chars (URL/path safe by construction)
    assert len(meta["id"]) == 32
    assert all(c in "0123456789abcdef" for c in meta["id"])

    bucket.blob.assert_called_once_with(f"{ha.GCS_PREFIX}{meta['id']}")
    blob = bucket.blob.return_value
    blob.upload_from_string.assert_called_once()
    _, kwargs = blob.upload_from_string.call_args
    assert kwargs.get("content_type") == "image/jpeg"


def test_save_attachment_pdf_kind():
    bucket = _mock_bucket()
    with patch.object(ha, "_get_bucket", return_value=bucket):
        meta = ha.save_attachment(_PDF, "application/pdf", "doc.pdf")
    assert meta["kind"] == "pdf"


@pytest.mark.parametrize("data,mime", [
    (_PNG, "image/png"),
    (_GIF, "image/gif"),
    (_WEBP, "image/webp"),
])
def test_save_attachment_accepts_all_whitelisted_image_types(data, mime):
    bucket = _mock_bucket()
    with patch.object(ha, "_get_bucket", return_value=bucket):
        meta = ha.save_attachment(data, mime, "f")
    assert meta["kind"] == "image"


def test_save_attachment_rejects_unknown_mime():
    with pytest.raises(ValueError, match="[Uu]nsupported"):
        ha.save_attachment(b"MZ\x90\x00", "application/x-msdownload", "evil.exe")


def test_save_attachment_rejects_oversize():
    big = b"\xff\xd8\xff" + b"0" * (ha.MAX_ATTACHMENT_BYTES + 1)
    with pytest.raises(ValueError, match="[Tt]oo large"):
        ha.save_attachment(big, "image/jpeg", "huge.jpg")


def test_save_attachment_rejects_magic_byte_mismatch():
    """A PDF payload claiming to be a JPEG must be rejected (content sniff)."""
    with pytest.raises(ValueError, match="content"):
        ha.save_attachment(_PDF, "image/jpeg", "fake.jpg")


def test_save_attachment_rejects_empty():
    with pytest.raises(ValueError):
        ha.save_attachment(b"", "image/jpeg", "empty.jpg")


# ------------------------------------------------------------------ #
# load_attachment                                                    #
# ------------------------------------------------------------------ #

def test_load_attachment_roundtrip():
    bucket = _mock_bucket()
    blob = bucket.blob.return_value
    blob.exists.return_value = True
    blob.download_as_bytes.return_value = _JPEG
    blob.content_type = "image/jpeg"
    blob.metadata = {"filename": "photo.jpg"}

    att_id = "a" * 32
    with patch.object(ha, "_get_bucket", return_value=bucket):
        data, mime, filename = ha.load_attachment(att_id)

    assert data == _JPEG
    assert mime == "image/jpeg"
    assert filename == "photo.jpg"
    bucket.blob.assert_called_once_with(f"{ha.GCS_PREFIX}{att_id}")


def test_load_attachment_rejects_malformed_id():
    """Non-hex / wrong-length ids never touch GCS (path-traversal guard)."""
    for bad in ("../secrets", "A" * 32, "b" * 31, "", "b" * 33):
        with pytest.raises(ValueError):
            ha.load_attachment(bad)


def test_load_attachment_missing_blob_raises_filenotfound():
    bucket = _mock_bucket()
    bucket.blob.return_value.exists.return_value = False
    with patch.object(ha, "_get_bucket", return_value=bucket):
        with pytest.raises(FileNotFoundError):
            ha.load_attachment("c" * 32)


# ------------------------------------------------------------------ #
# _get_bucket wiring                                                 #
# ------------------------------------------------------------------ #

def test_get_bucket_uses_chat_logs_bucket_env(monkeypatch):
    """Bucket comes from CHAT_LOGS_BUCKET — no new deploy env var needed."""
    ha._reset_client_cache_for_tests()
    fake_client = MagicMock(name="client")
    fake_storage = MagicMock()
    fake_storage.Client.return_value = fake_client
    fake_cloud = MagicMock()
    fake_cloud.storage = fake_storage
    fake_google = MagicMock()
    fake_google.cloud = fake_cloud

    import sys
    with patch.dict(sys.modules, {
        "google": fake_google,
        "google.cloud": fake_cloud,
        "google.cloud.storage": fake_storage,
    }):
        with patch.dict(os.environ, {"CHAT_LOGS_BUCKET": "klaus-chat-logs-test"}):
            bucket = ha._get_bucket()
    fake_client.bucket.assert_called_once_with("klaus-chat-logs-test")
    assert bucket is fake_client.bucket.return_value
    ha._reset_client_cache_for_tests()
