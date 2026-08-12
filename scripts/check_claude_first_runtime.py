"""Fail CI when deployable sources regain retired runtime dependencies."""
from __future__ import annotations

import argparse
import ast
from pathlib import Path


_FORBIDDEN_MARKERS = (
    "anthropic",
    "openai",
    "deepseek",
    "groq",
    "telegram",
    "TELEGRAM_BOT_TOKEN",
    "tiktoken",
    "SMART_AGENT",
    "WORKER_AGENT",
    "TICK_BRAIN",
    "KLAUS_LEGACY_RUNTIME_ENABLED",
    "KLAUS_HUB_CHAT_ENABLED",
    "OCCASION_CASCADE",
    "LLM_TIMEOUT_SECONDS",
    "gemini-3.5",
    "gpt-oss",
)
_SKIPPED_PREFIXES = (".git/", "frontend/", ".venv/", "tests/", ".superpowers/", "docs/", ".planning/", ".pytest_cache/")


def _is_scanned(relative: Path) -> bool:
    """Return whether a repository file is a deployable/current text artifact."""
    value = relative.as_posix()
    if value.startswith(_SKIPPED_PREFIXES):
        return False
    return relative.suffix in {".py", ".yml", ".yaml", ".txt"} or relative.name in {"Dockerfile", ".env.example", "requirements.txt"}


def find_violations(root: Path) -> list[str]:
    """Return every forbidden legacy marker found in active repository files."""
    violations: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if not _is_scanned(relative):
            continue
        if relative == Path("scripts/check_claude_first_runtime.py"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if path.suffix == ".py":
            try:
                tree = ast.parse(text)
            except SyntaxError as exc:
                violations.append(f"{relative}: invalid Python ({exc.msg})")
                continue
            imports = {
                name.name.split(".", 1)[0]
                for node in ast.walk(tree) if isinstance(node, ast.Import)
                for name in node.names
            } | {
                (node.module or "").split(".", 1)[0]
                for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
            }
            for marker in ("anthropic", "openai", "telegram", "tiktoken"):
                if marker in imports:
                    violations.append(f"{relative}: forbidden SDK import {marker}")
        else:
            for marker in _FORBIDDEN_MARKERS:
                if marker.lower() in text.lower():
                    violations.append(f"{relative}: forbidden marker {marker}")
    return violations


def main() -> int:
    """Run the subtraction guard as a CI/deploy command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    violations = find_violations(args.root.resolve())
    if violations:
        print("Claude-first runtime guard failed:")
        print("\n".join(violations))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
