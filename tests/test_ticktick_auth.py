"""Unit tests for mcp_tools/ticktick_auth.py."""
from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest


# ------------------------------------------------------------------ #
# FileTickTickTokenStore                                             #
# ------------------------------------------------------------------ #

class TestFileTickTickTokenStore:
    def test_load_returns_none_if_file_absent(self, tmp_path):
        from mcp_tools.ticktick_auth import FileTickTickTokenStore
        store = FileTickTickTokenStore(str(tmp_path / "tokens.json"))
        assert store.load() is None

    def test_save_and_load_roundtrip(self, tmp_path):
        from mcp_tools.ticktick_auth import FileTickTickTokenStore
        path = str(tmp_path / "tokens.json")
        store = FileTickTickTokenStore(path)
        tokens = {"access_token": "acc", "refresh_token": "ref"}
        store.save(tokens)
        assert store.load() == tokens

    def test_load_returns_none_on_corrupt_file(self, tmp_path):
        from mcp_tools.ticktick_auth import FileTickTickTokenStore
        path = tmp_path / "tokens.json"
        path.write_text("not json")
        store = FileTickTickTokenStore(str(path))
        assert store.load() is None


# ------------------------------------------------------------------ #
# get_valid_access_token                                             #
# ------------------------------------------------------------------ #

class TestGetValidAccessToken:
    def setup_method(self):
        import mcp_tools.ticktick_auth as auth_mod
        auth_mod._token_cache = None

    def test_returns_token_from_file_store(self, tmp_path, monkeypatch):
        import mcp_tools.ticktick_auth as auth_mod
        tokens = {"access_token": "valid_acc", "refresh_token": "ref"}
        token_path = str(tmp_path / "tokens.json")
        import json
        with open(token_path, "w") as f:
            json.dump(tokens, f)

        monkeypatch.setenv("TICKTICK_TOKEN_STORAGE", "file")
        monkeypatch.setenv("TICKTICK_TOKEN_PATH", token_path)

        from mcp_tools.ticktick_auth import get_valid_access_token
        assert get_valid_access_token() == "valid_acc"

    def test_raises_if_no_tokens(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TICKTICK_TOKEN_STORAGE", "file")
        monkeypatch.setenv("TICKTICK_TOKEN_PATH", str(tmp_path / "missing.json"))

        from mcp_tools.ticktick_auth import get_valid_access_token
        with pytest.raises(RuntimeError, match="No TickTick tokens"):
            get_valid_access_token()

    def test_cache_is_reused_on_second_call(self, tmp_path, monkeypatch):
        import mcp_tools.ticktick_auth as auth_mod
        auth_mod._token_cache = {"access_token": "cached", "refresh_token": "r"}

        monkeypatch.setenv("TICKTICK_TOKEN_STORAGE", "file")
        monkeypatch.setenv("TICKTICK_TOKEN_PATH", str(tmp_path / "x.json"))

        from mcp_tools.ticktick_auth import get_valid_access_token
        # Should return cached value without reading file
        assert get_valid_access_token() == "cached"


# ------------------------------------------------------------------ #
# refresh_and_persist                                                #
# ------------------------------------------------------------------ #

class TestRefreshAndPersist:
    def setup_method(self):
        import mcp_tools.ticktick_auth as auth_mod
        auth_mod._token_cache = None

    def test_refresh_updates_cache(self, tmp_path, monkeypatch):
        import mcp_tools.ticktick_auth as auth_mod
        old_tokens = {"access_token": "old", "refresh_token": "ref"}
        new_tokens = {"access_token": "new_acc", "refresh_token": "new_ref"}
        auth_mod._token_cache = old_tokens

        token_path = str(tmp_path / "tokens.json")
        with open(token_path, "w") as f:
            import json
            json.dump(old_tokens, f)

        monkeypatch.setenv("TICKTICK_TOKEN_STORAGE", "file")
        monkeypatch.setenv("TICKTICK_TOKEN_PATH", token_path)
        monkeypatch.setenv("TICKTICK_CLIENT_ID", "cid")
        monkeypatch.setenv("TICKTICK_CLIENT_SECRET", "csec")

        with patch("mcp_tools.ticktick_auth._do_refresh", return_value=new_tokens):
            from mcp_tools.ticktick_auth import refresh_and_persist
            result = refresh_and_persist()

        assert result == "new_acc"
        assert auth_mod._token_cache["access_token"] == "new_acc"

    def test_refresh_raises_without_refresh_token(self, tmp_path, monkeypatch):
        import mcp_tools.ticktick_auth as auth_mod
        auth_mod._token_cache = {"access_token": "old", "refresh_token": ""}

        monkeypatch.setenv("TICKTICK_TOKEN_STORAGE", "file")
        monkeypatch.setenv("TICKTICK_TOKEN_PATH", str(tmp_path / "x.json"))

        from mcp_tools.ticktick_auth import refresh_and_persist
        with pytest.raises(RuntimeError, match="No refresh token"):
            refresh_and_persist()


# ------------------------------------------------------------------ #
# build_token_store_from_env                                        #
# ------------------------------------------------------------------ #

class TestBuildTokenStoreFromEnv:
    def test_file_backend_default(self, monkeypatch, tmp_path):
        monkeypatch.delenv("TICKTICK_TOKEN_STORAGE", raising=False)
        from mcp_tools.ticktick_auth import build_token_store_from_env, FileTickTickTokenStore
        store = build_token_store_from_env()
        assert isinstance(store, FileTickTickTokenStore)

    def test_unknown_backend_raises(self, monkeypatch):
        monkeypatch.setenv("TICKTICK_TOKEN_STORAGE", "redis")
        from mcp_tools.ticktick_auth import build_token_store_from_env
        with pytest.raises(ValueError, match="Unknown"):
            build_token_store_from_env()
