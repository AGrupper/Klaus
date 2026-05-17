"""Agent orchestrator — dual-model coordination logic.

Claude (Smart Agent) receives every user message, makes all judgment calls,
and crafts every JARVIS-style response. Gemini Flash (Worker Agent) executes
tools and gathers data on Claude's behalf via two delegation paths:

  Path A — Delegate + Review:
    Claude delegates via delegate_to_worker (respond_directly=false)
    → Flash executes tools → result returned to Claude → Claude responds.

  Path B — Flash Solo:
    Claude delegates via delegate_to_worker (respond_directly=true)
    → Flash handles the request end-to-end → response goes directly to user.

Conversation history storage is pluggable via the ConversationStore protocol:
  - InMemoryConversationStore: default for local dev (no persistence).
  - FirestoreConversationStore: Cloud Run (survives scale-to-zero evictions).

Select the backend with CONVERSATION_STORE=memory|firestore (default: memory).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from core.llm_client import LLMClient, LLMError
from core import tools as tool_registry

load_dotenv()

logger = logging.getLogger(__name__)

ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")

# Safety valve: abort tool-use loops after this many iterations.
MAX_TOOL_ITERATIONS = 8

# Per-user conversation history is capped at this many turns (user+assistant = 2 messages).
MAX_CONVERSATION_TURNS = 50


# ------------------------------------------------------------------ #
# ConversationStore protocol + backends                              #
# ------------------------------------------------------------------ #

@runtime_checkable
class ConversationStore(Protocol):
    """Protocol for pluggable per-user conversation history backends."""

    def get(self, user_id: int) -> list[dict]:
        """Return the stored message list for user_id (newest-last order)."""
        ...

    def append(self, user_id: int, role: str, content: str) -> None:
        """Append one message and enforce the configured message cap."""
        ...

    def clear(self, user_id: int) -> None:
        """Wipe conversation history for user_id (e.g. on /reset)."""
        ...


class InMemoryConversationStore:
    """In-memory per-user conversation history (default for local dev).

    History is lost on process restart. Suitable for development and
    local long-poll mode where the process runs continuously.
    """

    def __init__(self, max_turns: int = MAX_CONVERSATION_TURNS) -> None:
        self._max_messages = max_turns * 2  # each turn = 1 user + 1 assistant msg
        self._timeout = timedelta(hours=int(os.getenv("SESSION_TIMEOUT_HOURS", "6")))
        # values: {"messages": list[dict], "updated_at": datetime}
        self._histories: dict[int, dict] = {}

    def get(self, user_id: int) -> list[dict]:
        entry = self._histories.get(user_id)
        if entry is None:
            return []
        if datetime.now(timezone.utc) - entry["updated_at"] > self._timeout:
            self._histories.pop(user_id, None)
            return []
        return list(entry["messages"])

    def append(self, user_id: int, role: str, content: str) -> None:
        now = datetime.now(timezone.utc)
        entry = self._histories.get(user_id)
        if entry is None or now - entry["updated_at"] > self._timeout:
            messages: list[dict] = []
        else:
            messages = list(entry["messages"])
        messages.append({"role": role, "content": content})
        # WHY: keep newest messages — they carry the most relevant context.
        if len(messages) > self._max_messages:
            messages = messages[-self._max_messages:]
        self._histories[user_id] = {"messages": messages, "updated_at": now}

    def clear(self, user_id: int) -> None:
        self._histories.pop(user_id, None)


# Keep the old name as an alias so external code referencing ConversationManager
# continues to work without modification.
ConversationManager = InMemoryConversationStore


def build_conversation_store_from_env() -> ConversationStore:
    """Construct the conversation store backend selected by CONVERSATION_STORE.

    ``"memory"`` (default):
        `InMemoryConversationStore` — no persistence, suitable for local dev.

    ``"firestore"``:
        `FirestoreConversationStore` — persists in Firestore, required for
        Cloud Run where containers scale to zero between messages.
        Reads GCP_PROJECT_ID and FIRESTORE_DATABASE from env.

    Raises:
        KeyError: If CONVERSATION_STORE is ``"firestore"`` but GCP_PROJECT_ID
            is not set.
        ValueError: If CONVERSATION_STORE is set to an unrecognised value.
    """
    backend = os.getenv("CONVERSATION_STORE", "memory")

    if backend == "memory":
        return InMemoryConversationStore()

    if backend == "firestore":
        from memory.firestore_conversation import FirestoreConversationStore
        project_id = os.environ["GCP_PROJECT_ID"]
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        collection = os.getenv("FIRESTORE_COLLECTION_CONVERSATIONS", "conversations")
        return FirestoreConversationStore(
            project_id=project_id,
            collection=collection,
            database=database,
        )

    raise ValueError(
        f"Unknown CONVERSATION_STORE value: {backend!r}. "
        "Expected 'memory' or 'firestore'."
    )


class AgentOrchestrator:
    """Coordinates Smart Agent and Worker Agent with optional fallback.

    The Smart Agent (primary: Gemini 3 Flash, fallback: Claude Haiku) receives
    every user message, makes judgment calls, and crafts responses.
    The Worker Agent (Gemini 2.5 Flash) executes tools on the Smart Agent's behalf.

    If the primary Smart Agent's API returns an error (e.g. overload, outage),
    the orchestrator automatically retries the request using the fallback model.

    Instantiate once at startup and share across all user sessions. The
    LLMClient instances are stateless after construction; conversation state
    is managed by ConversationManager.
    """

    def __init__(self) -> None:
        # WHY: both clients are initialised from environment variables so the
        # model IDs and API keys can be changed without touching code.
        self.smart_agent = LLMClient(
            backend=os.environ["SMART_AGENT_BACKEND"],
            model=os.environ["SMART_AGENT_MODEL"],
            api_key=os.environ["SMART_AGENT_API_KEY"],
        )
        self.worker_agent = LLMClient(
            backend=os.environ["WORKER_AGENT_BACKEND"],
            model=os.environ["WORKER_AGENT_MODEL"],
            api_key=os.environ["WORKER_AGENT_API_KEY"],
        )

        # WHY: fallback Smart Agent is optional — if the env vars are not set,
        # the orchestrator degrades gracefully to the old single-model behavior.
        fb_backend = os.environ.get("SMART_AGENT_FALLBACK_BACKEND")
        fb_model = os.environ.get("SMART_AGENT_FALLBACK_MODEL")
        fb_key = os.environ.get("SMART_AGENT_FALLBACK_API_KEY")
        if fb_backend and fb_model and fb_key:
            self.smart_agent_fallback: LLMClient | None = LLMClient(
                backend=fb_backend, model=fb_model, api_key=fb_key,
            )
            logger.info(
                "Smart Agent fallback configured: %s / %s",
                fb_backend, fb_model,
            )
        else:
            self.smart_agent_fallback = None

        # Load prompts from disk at startup — avoids repeated file I/O per message.
        self._smart_prompt_template = _load_prompt("prompts/smart_agent.md")
        self._worker_prompt_template = _load_prompt("prompts/worker_agent.md")

        self.conversation_manager = build_conversation_store_from_env()

    def handle_message(self, user_message: str, user_id: int) -> str:
        """Process one user message through the full dual-model pipeline.

        Args:
            user_message: Raw text from the user interface.
            user_id: Unique identifier for the user (Telegram ID or similar).

        Returns:
            The agent's final response string, ready to send to the user.
        """
        # WHY: memory tools (remember/recall) need the user_id but the tool
        # dispatch signature does not pass it. A thread-local is safe here
        # because handle_message always runs in asyncio.to_thread — each call
        # gets its own thread from the pool.
        tool_registry.set_current_user_id(user_id)

        # Inject today's date in Israel time so the agent has accurate temporal context.
        today_label = _today_israel()
        smart_system = self._smart_prompt_template.replace("{today_date}", today_label)
        worker_system = self._worker_prompt_template.replace("{today_date}", today_label)

        # Persist the incoming message and get the full history for this session.
        self.conversation_manager.append(user_id, "user", user_message)
        messages = self.conversation_manager.get(user_id)

        # Run Claude's orchestration loop.
        response_text = self._run_smart_loop(
            messages, smart_system, worker_system
        )

        # Persist Claude's final text response.
        self.conversation_manager.append(user_id, "assistant", response_text)
        return response_text

    # ------------------------------------------------------------------ #
    # Smart Agent loop (Claude)                                          #
    # ------------------------------------------------------------------ #

    def _run_smart_loop(self, messages: list[dict], smart_system: str,
                        worker_system: str) -> str:
        """Run Claude's tool-use loop until it produces a final text response.

        Claude may call delegate_to_worker one or more times. Each call is
        intercepted here and routed to _run_worker_loop(). Tool results are
        fed back to Claude so it can reason and respond.
        """
        # Work on a local copy so the conversation manager's history is not
        # polluted with intermediate tool_use / tool_result messages.
        current_messages = list(messages)

        for iteration in range(MAX_TOOL_ITERATIONS):
            try:
                response = self.smart_agent.chat(
                    current_messages,
                    system=smart_system,
                    tools=tool_registry.get_all_schemas(),
                )
            except LLMError as exc:
                logger.warning(
                    "Smart agent PRIMARY error (iter %d): %s", iteration, exc,
                )
                # Attempt the fallback model if one is configured.
                if self.smart_agent_fallback is not None:
                    try:
                        logger.info("Retrying with Smart Agent fallback…")
                        try:
                            from memory.firestore_db import increment_fallback_counter
                            increment_fallback_counter()
                        except Exception:
                            logger.debug("fallback counter increment failed", exc_info=True)
                        response = self.smart_agent_fallback.chat(
                            current_messages,
                            system=smart_system,
                            tools=tool_registry.get_all_schemas(),
                        )
                    except LLMError as fallback_exc:
                        logger.error(
                            "Smart agent FALLBACK also failed (iter %d): %s",
                            iteration, fallback_exc,
                        )
                        return (
                            "I'm afraid I encountered a connectivity issue, Sir. "
                            "Please try again in a moment."
                        )
                else:
                    return (
                        "I'm afraid I encountered a connectivity issue, Sir. "
                        "Please try again in a moment."
                    )

            tool_calls = response["tool_calls"]
            response_text = response["text"]

            # No tool calls → Claude has produced its final response.
            if not tool_calls:
                return response_text or ""

            # Build the full assistant message content block (text + tool_use blocks).
            # WHY: Anthropic requires the complete assistant message (including any
            # intermediate text) before the corresponding tool_result messages.
            assistant_content: list[dict] = []
            if response_text:
                assistant_content.append({"type": "text", "text": response_text})
            for tc in tool_calls:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": tc["input"],
                })
            current_messages.append({"role": "assistant", "content": assistant_content})

            # Process each tool call and collect results.
            tool_results: list[dict] = []

            for tc in tool_calls:
                tool_name = tc["name"]
                tool_id = tc["id"]
                tool_args = tc["input"]

                if tool_name == "delegate_to_worker":
                    task = tool_args.get("task", "")
                    respond_directly = bool(tool_args.get("respond_directly", False))

                    worker_response = self._run_worker_loop(task, worker_system)

                    if respond_directly:
                        # Path B: Flash solo — return immediately, no Claude review.
                        logger.info("Path B delegation: returning Flash response directly.")
                        return worker_response

                    # Path A: feed Flash's result back to Claude for review + crafting.
                    logger.info("Path A delegation: returning Flash result to Claude.")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": worker_response,
                    })

                else:
                    # WHY: remember/recall are always called directly by Claude —
                    # they require Claude's judgment and must not go via the worker.
                    # Any other direct tool call is unexpected; log a warning.
                    if tool_name not in tool_registry.SMART_AGENT_DIRECT_TOOLS:
                        logger.warning(
                            "Claude called tool '%s' directly (expected delegation).", tool_name
                        )
                    try:
                        result = tool_registry.dispatch(tool_name, tool_args)
                    except KeyError as exc:
                        result = json.dumps({"error": str(exc)})
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": result,
                    })

            # Append all tool results as a single user turn.
            # WHY: Anthropic's API allows multiple tool_result blocks in one user message;
            # grouping them avoids unnecessary turn-counting against Claude's context.
            if tool_results:
                current_messages.append({"role": "user", "content": tool_results})

        logger.error(
            "Smart loop exceeded MAX_TOOL_ITERATIONS (%d) without a final text response.",
            MAX_TOOL_ITERATIONS,
        )
        return (
            "Apologies, Sir. This request required more processing steps than expected. "
            "Please rephrase or break it into smaller parts."
        )

    # ------------------------------------------------------------------ #
    # Worker Agent loop (Gemini Flash)                                   #
    # ------------------------------------------------------------------ #

    def _run_worker_loop(self, task: str, worker_system: str) -> str:
        """Run Gemini Flash on a delegated task, managing its own tool-use loop.

        Args:
            task: Natural language instruction from Claude.
            worker_system: Rendered worker system prompt with today's date.

        Returns:
            Flash's final text response (fed back to Claude, or returned directly).
        """
        # WHY: Flash starts with a fresh single-message conversation — it only needs
        # the delegated task context, not Amit's full conversation history.
        worker_messages: list[dict] = [{"role": "user", "content": task}]

        for iteration in range(MAX_TOOL_ITERATIONS):
            try:
                response = self.worker_agent.chat(
                    worker_messages,
                    system=worker_system,
                    tools=tool_registry.get_worker_schemas(),
                )
            except LLMError as exc:
                logger.error("Worker agent error (iter %d): %s", iteration, exc)
                return f"Worker encountered an error and could not complete the task: {exc}"

            tool_calls = response["tool_calls"]
            response_text = response["text"]

            # No tool calls → Flash has produced its final result.
            if not tool_calls:
                return response_text or ""

            # Append Flash's tool_use message.
            worker_assistant_content: list[dict] = []
            if response_text:
                worker_assistant_content.append({"type": "text", "text": response_text})
            for tc in tool_calls:
                worker_assistant_content.append({
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": tc["input"],
                })
            worker_messages.append({"role": "assistant", "content": worker_assistant_content})

            # Execute tools and collect results.
            worker_tool_results: list[dict] = []
            for tc in tool_calls:
                try:
                    result = tool_registry.dispatch(tc["name"], tc["input"])
                except KeyError as exc:
                    result = json.dumps({"error": str(exc)})
                worker_tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc["id"],
                    "content": result,
                })

            worker_messages.append({"role": "user", "content": worker_tool_results})

        logger.error(
            "Worker loop exceeded MAX_TOOL_ITERATIONS (%d) without a final response.",
            MAX_TOOL_ITERATIONS,
        )
        return "Worker could not complete the task within the allotted steps."


# ------------------------------------------------------------------ #
# Module-level helpers                                               #
# ------------------------------------------------------------------ #

def _load_prompt(relative_path: str) -> str:
    """Load a prompt file relative to the project root.

    Raises:
        FileNotFoundError: If the prompt file does not exist.
    """
    path = Path(relative_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Prompt file not found: {path.resolve()}. "
            "Ensure you are running from the project root."
        )
    return path.read_text(encoding="utf-8").strip()


def _today_israel() -> str:
    """Return today's date in Israel time as a human-readable string.

    Example: 'Sunday, May 4, 2025'
    """
    now = datetime.now(tz=ISRAEL_TZ)
    return f"{now.strftime('%A')}, {now.strftime('%B')} {now.day}, {now.year}"
