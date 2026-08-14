"""Integration test for the Gemini embedding call used by MemoryStore.

Hits the real Gemini API. Requires the dedicated GEMINI_EMBEDDING_API_KEY
(loaded from .env via load_dotenv(override=True), per project convention).
Skipped automatically if the key is missing so non-integration runs are clean.
"""
import os
import pytest
from dotenv import load_dotenv

load_dotenv(override=True)

pytestmark = pytest.mark.skipif(
    not os.environ.get("GEMINI_EMBEDDING_API_KEY"),
    reason="Gemini embedding API key not set; skipping live embedding test",
)


def test_embed_returns_768_dim_vector():
    """End-to-end: real Gemini call returns a 768-dim float vector."""
    from memory.pinecone_db import MemoryStore
    store = MemoryStore(api_key="unused-for-this-test", index_name="unused")
    vec = store._embed("Amit's gym is on Mon/Wed/Fri", user_id="live-test")
    assert isinstance(vec, list)
    assert len(vec) == 768
    assert all(isinstance(x, float) for x in vec)
