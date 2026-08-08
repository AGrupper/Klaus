"""Credential-selection tests for the embedding-only Gemini dependency."""
from unittest.mock import MagicMock, patch

from memory.pinecone_db import MemoryStore


def test_embedding_key_prefers_dedicated_environment_variable(monkeypatch):
    """The v7 credential wins even while the deployment alias remains accepted."""
    monkeypatch.setenv("GEMINI_EMBEDDING_API_KEY", "embedding-key")
    monkeypatch.setenv("SMART_AGENT_API_KEY", "legacy-key")
    store = MemoryStore(api_key="pinecone", index_name="index")

    with patch("google.genai.Client", return_value=MagicMock()) as client:
        store._get_genai()

    client.assert_called_once_with(api_key="embedding-key")


def test_embedding_key_temporarily_falls_back_to_legacy_variable(monkeypatch):
    """Rolling deploys keep embeddings alive until Secret Manager is renamed."""
    monkeypatch.delenv("GEMINI_EMBEDDING_API_KEY", raising=False)
    monkeypatch.setenv("SMART_AGENT_API_KEY", "legacy-key")
    store = MemoryStore(api_key="pinecone", index_name="index")

    with patch("google.genai.Client", return_value=MagicMock()) as client:
        store._get_genai()

    client.assert_called_once_with(api_key="legacy-key")


def test_embedding_call_records_provider_usage_with_configured_rate(monkeypatch):
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    monkeypatch.setenv("FIRESTORE_DATABASE", "test-db")
    monkeypatch.setenv("GEMINI_EMBEDDING_COST_PER_MILLION_TOKENS", "0.20")
    monkeypatch.setenv("KLAUS_EMBEDDING_METER_ENABLED", "true")
    store = MemoryStore(api_key="pinecone", index_name="index")
    response = MagicMock()
    response.embeddings = [MagicMock(values=[0.1] * 768)]
    response.usage_metadata.prompt_token_count = 250
    store._genai = MagicMock()
    store._genai.models.embed_content.return_value = response

    usage = MagicMock()
    with patch("memory.firestore_db.EmbeddingUsageStore", return_value=usage):
        store._embed("remember this")

    usage.record.assert_called_once_with(
        input_tokens=250,
        item_count=1,
        cost_usd=0.00005,
    )
