"""Tests for core/prompt_loader.py — the shared cached prompt loader."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from core import prompt_loader


@pytest.fixture(autouse=True)
def _clear_cache():
    """Each test starts with a cold cache and leaves a clean one behind."""
    prompt_loader.load_prompt.cache_clear()
    yield
    prompt_loader.load_prompt.cache_clear()


class TestLoadPrompt:
    def test_loads_and_strips_prompt_file(self, tmp_path, monkeypatch):
        prompt_file = tmp_path / "prompts" / "example.md"
        prompt_file.parent.mkdir()
        prompt_file.write_text("Hello Klaus.\n\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        assert prompt_loader.load_prompt("prompts/example.md") == "Hello Klaus."

    def test_missing_file_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            prompt_loader.load_prompt("prompts/does-not-exist.md")

    def test_second_call_served_from_cache(self, tmp_path, monkeypatch):
        prompt_file = tmp_path / "prompts" / "cached.md"
        prompt_file.parent.mkdir()
        prompt_file.write_text("cached content", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        with patch.object(
            Path, "read_text", wraps=Path.read_text, autospec=True
        ) as mock_read:
            first = prompt_loader.load_prompt("prompts/cached.md")
            second = prompt_loader.load_prompt("prompts/cached.md")

        assert first == second == "cached content"
        assert mock_read.call_count == 1

    def test_real_prompt_files_load_via_delegates(self):
        """The thin delegates in core.main / core.autonomous resolve real prompts."""
        from core import autonomous, main

        assert main._load_prompt("prompts/smart_agent.md")
        assert autonomous._load_prompt("prompts/autonomous.md")
