"""Integration test for the Gemini embedding call used by MemoryStore.

Hits the real Gemini API. Requires GEMINI_EMBEDDING_API_KEY (preferred) or the
temporary SMART_AGENT_API_KEY compatibility alias in env (loaded from .env via
load_dotenv(override=True), per project convention).
Skipped automatically if the key is missing so non-integration runs are clean.
"""
import os
import pytest
from dotenv import load_dotenv

load_dotenv(override=True)

pytestmark = pytest.mark.skipif(
    not (
        os.environ.get("GEMINI_EMBEDDING_API_KEY")
        or os.environ.get("SMART_AGENT_API_KEY")
    ),
    reason="Gemini embedding API key not set; skipping live embedding test",
)


def test_embed_returns_768_dim_vector():
    """End-to-end: real Gemini call returns a 768-dim float vector."""
    from memory.pinecone_db import MemoryStore
    store = MemoryStore(api_key="unused-for-this-test", index_name="unused")
    vec = store._embed("Amit's gym is on Mon/Wed/Fri")
    assert isinstance(vec, list)
    assert len(vec) == 768
    assert all(isinstance(x, float) for x in vec)


def test_embed_batch_returns_one_768_dim_vector_per_text():
    """End-to-end: a single batched Gemini call embeds N texts in order."""
    from memory.pinecone_db import MemoryStore
    store = MemoryStore(api_key="unused-for-this-test", index_name="unused")
    vecs = store._embed_batch([
        "Amit's gym is on Mon/Wed/Fri",
        "Klaus runs on Cloud Run in me-west1",
        "The marathon plan peaks at 70km per week",
    ])
    assert len(vecs) == 3
    for vec in vecs:
        assert len(vec) == 768
        assert all(isinstance(x, float) for x in vec)
