"""Agent orchestrator — dual-model coordination logic.

Gemini 3.5 Flash (Smart Agent) receives every user message, makes all judgment
calls, and crafts every response. DeepSeek V4 Flash (Worker Agent) executes
tools and gathers data on the Smart Agent's behalf via two delegation paths:

  Path A — Delegate + Review:
    Smart Agent delegates via delegate_to_worker (respond_directly=false)
    → Worker executes tools → result returned to Smart Agent → Smart Agent responds.

  Path B — Worker Solo:
    Smart Agent delegates via delegate_to_worker (respond_directly=true)
    → Worker handles the request end-to-end → response goes directly to user.

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
from core import prompt_loader
from core import tools as tool_registry
from memory.firestore_db import SelfStateStore, JournalStore, UserProfileStore

load_dotenv(override=True)

logger = logging.getLogger(__name__)

ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")

# Safety valve: abort tool-use loops after this many iterations.
# Raised from 8 → 12 for data-heavy Phase-24 coaching queries that legitimately
# need ~6 tool calls (blueprint + block status + benchmark + nutrition + training
# history + coaching guide) before the brain can compose a substantive answer.
MAX_TOOL_ITERATIONS = 12

# Per-user conversation history is capped at this many turns (user+assistant = 2 messages).
MAX_CONVERSATION_TURNS = 50

# Canned message returned by ``_run_smart_loop`` on total LLM exhaustion
# (primary + fallback both failed). Exported so the autonomous tick
# (``core.autonomous._SMART_LOOP_ERROR_SENTINELS``) can detect it as a Layer-2
# failure and engage D-19 fallback to the tick-brain draft. Any edit here MUST
# preserve the substring asserted by
# ``tests/test_autonomous.py::test_sentinel_substring_matches_main_constant``.
CONNECTIVITY_ERROR_TEXT = (
    "I'm afraid I encountered a connectivity issue, Sir. "
    "Please try again in a moment."
)


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

    The Smart Agent (primary: Gemini 3.5 Flash, fallback: Claude Haiku) receives
    every user message, makes judgment calls, and crafts responses.
    The Worker Agent (DeepSeek V4 Flash) executes tools on the Smart Agent's behalf.

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
            base_url=os.environ.get("WORKER_AGENT_BASE_URL"),
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

        # Nutrition fueling-coach guidance — appended to the smart_system in the
        # CHAT path (handle_message) so on-demand nutrition answers get the same
        # performance-fueling coaching the morning briefing / autonomous tick
        # already inject. Load defensively: a missing file must NOT crash chat.
        try:
            self._meal_audit_content = _load_prompt("prompts/meal_audit.md")
        except FileNotFoundError:
            logger.warning("meal_audit.md not found — nutrition coaching disabled in chat")
            self._meal_audit_content = ""

        self.conversation_manager = build_conversation_store_from_env()

        # Load SELF.md content once at startup for stable prompt injection.
        # Per D-03: injected into smart_system only; stable content is placed
        # before dynamic content ({today_date}) for Gemini prompt caching.
        self._self_md_content = _load_self_md()

        # Load slim coaching guide digest once at startup.
        # Per D-04: only the slim core digest (~200-300 lines) is injected as a
        # stable cached prefix. The full guide is read on-demand by read_coaching_guide().
        self._coaching_guide_content = _load_coaching_guide_slim()

        # Bootstrap self_state in Firestore on first startup (D-04).
        # If the config/self_state doc doesn't exist, seed it with identity_summary
        # from SELF.md intro paragraph. Never blocks startup on failure.
        self._self_state_store = _build_self_state_store()
        if self._self_state_store is not None:
            self._self_state_store.bootstrap_if_empty(
                identity_summary=_extract_intro_paragraph(self._self_md_content)
            )

        # PHASE 19 (Plan 02) — bootstrap users/amit with empty scaffold on first
        # startup. Pitfall 7: bootstrap_if_empty MUST never raise — handled
        # internally by the store. Sibling of SelfStateStore bootstrap above.
        self._user_profile_store = _build_user_profile_store()
        if self._user_profile_store is not None:
            self._user_profile_store.bootstrap_if_empty()

        self._journal_store = _build_journal_store()

    def render_smart_system(self, template: str) -> str:
        """Render a smart_system template by substituting all standard placeholders.

        Resolves: ``{self_md}``, ``{self_state}``, ``{journal_digest}``, ``{today_date}``.
        Empty stores (None) substitute empty strings — NOT literal placeholders.

        Used by:
          - ``handle_message`` (per-message chat path)
          - ``core/autonomous.py:_compose_layer2`` (per-tick autonomous path) — Plan 18-06

        Stable content (``self_md``) is placed before dynamic content for Gemini
        prompt caching.
        """
        # Assemble the smart_system prompt with stable content first, then dynamic.
        # Stable-first ordering enables Gemini prompt caching on the shared prefix.
        today_label = _today_israel()

        # Build self_state snippet — omit blank fields per D-05.
        self_state_snippet = ""
        if self._self_state_store is not None:
            state = self._self_state_store.get()
            non_empty = {k: v for k, v in state.items()
                         if k not in ("updated_at", "bootstrapped_at") and v}
            if non_empty:
                lines = ["**Self-state:**"]
                for key, value in non_empty.items():
                    lines.append(f"- {key}: {value}")
                self_state_snippet = "\n".join(lines)

        # Build journal_digest — last ~3 entries, newest-first, one line each.
        # Omit the block entirely when empty (D-15 empty-state rule).
        journal_digest = ""
        if self._journal_store is not None:
            entries = self._journal_store.get_recent(3)        # newest-first
            if entries:
                lines = ["**Recent journal:**"]
                for e in entries:
                    line = f"- {e.get('date','')} (mood: {e.get('mood','')}): {e.get('summary','')}"
                    highlights = e.get("highlights") or []
                    if highlights:
                        line += f" | {highlights[0]}"
                    lines.append(line)
                journal_digest = "\n".join(lines)
            # else: leave "" — empty-state rule omits the block entirely

        # PHASE 19/21 — training profile block (PROMPT-01, reframed in Plan 21-04)
        # Same omit-empty discipline as self_state: empty profile → empty snippet,
        # NOT a literal placeholder. The prompt instructs "ask the user" when blank.
        # Phase 21 Plan 04: replaced raw k:v dump with coaching-reference prose that
        # formats structured fields (dated_goals, weekly_split, nutrition_targets,
        # plan_start_date, supplement_schedule, fueling_timeline) as a readable guide.
        # Unknown/future keys fall back to the generic "- k: v" line (forward-compat).
        training_profile_snippet = ""
        if getattr(self, "_user_profile_store", None) is not None:
            profile = self._user_profile_store.load()
            non_empty = {
                k: v for k, v in profile.items()
                if k not in ("updated_at", "bootstrapped_at", "schema_version") and v
            }
            if non_empty:
                # Known structured keys — rendered as coaching-reference prose.
                _KNOWN_KEYS = frozenset({
                    "dated_goals", "weekly_split", "nutrition_targets",
                    "supplement_schedule", "fueling_timeline", "plan_start_date",
                    # v3.0 legacy fields — rendered via fallback below if still present
                })
                lines = ["**Coaching reference — Amit's training plan:**"]

                # dated_goals — Tier A peak targets: one bullet per goal
                if dated_goals := non_empty.get("dated_goals"):
                    lines.append("Goals:")
                    for g in dated_goals:
                        label = g.get("goal_label", "Goal")
                        date = g.get("target_date", "")
                        metrics = g.get("metrics") or []
                        # metrics is a dict {metric_name: target} per the ingest
                        # contract (scripts/ingest_blueprint.py); a list of strings
                        # is also accepted for forward-compat. Iterating a dict
                        # directly would drop every target value (CR-21-01).
                        if isinstance(metrics, dict):
                            metric_str = ", ".join(f"{k} {v}" for k, v in metrics.items())
                        else:
                            metric_str = ", ".join(str(m) for m in metrics) if metrics else ""
                        line = f"  - {label}"
                        if date:
                            line += f" ({date})"
                        if metric_str:
                            line += f": {metric_str}"
                        lines.append(line)

                # weekly_split — flexible template (label + modality + priority, no attendance)
                if weekly_split := non_empty.get("weekly_split"):
                    lines.append("Weekly split (template — label / modality / priority):")
                    for day, slots in weekly_split.items():
                        am = slots.get("am") or {} if isinstance(slots, dict) else {}
                        pm = slots.get("pm") or {} if isinstance(slots, dict) else {}
                        am_label = am.get("label", "—")
                        am_mod = am.get("modality", "")
                        am_pri = am.get("priority", "")
                        pm_label = pm.get("label", "—")
                        pm_mod = pm.get("modality", "")
                        pm_pri = pm.get("priority", "")
                        am_str = am_label
                        if am_mod:
                            am_str += f" [{am_mod}]"
                        if am_pri:
                            am_str += f" · {am_pri}"
                        pm_str = pm_label
                        if pm_mod:
                            pm_str += f" [{pm_mod}]"
                        if pm_pri:
                            pm_str += f" · {pm_pri}"
                        lines.append(f"  {day}: AM {am_str} / PM {pm_str}")

                # nutrition_targets — daily macro targets + fueling slots
                if nutrition_targets := non_empty.get("nutrition_targets"):
                    if isinstance(nutrition_targets, dict):
                        protein_g = nutrition_targets.get("protein_g", "")
                        carbs_g = nutrition_targets.get("carbs_g", "")
                        parts = []
                        if protein_g:
                            parts.append(f"{protein_g}g protein")
                        if carbs_g:
                            parts.append(f"{carbs_g}g carbs")
                        macro_str = " / ".join(parts) if parts else str(nutrition_targets)
                        lines.append(f"Daily targets: {macro_str}")
                        # Directional aerobic note deliberately preserved during
                        # ingest (the locked v4.0 narrowing) — surface it so it is
                        # not silently dropped (WR-21-01).
                        aerobic_note = nutrition_targets.get("aerobic_reference_note")
                        if aerobic_note:
                            lines.append(f"  Aerobic reference: {aerobic_note}")
                        fueling_slots = nutrition_targets.get("fueling_slots")
                        if fueling_slots:
                            lines.append(f"  Fueling slots: {', '.join(str(s) for s in fueling_slots)}")
                    else:
                        lines.append(f"  Nutrition targets: {nutrition_targets}")

                # fueling_timeline — ordered slot list
                if fueling_timeline := non_empty.get("fueling_timeline"):
                    lines.append("Fueling timeline:")
                    for i, slot in enumerate(fueling_timeline, 1):
                        if isinstance(slot, dict):
                            timing = slot.get("timing", "")
                            food = slot.get("food", "")
                            slot_str = f"  Slot {i}"
                            if timing:
                                slot_str += f" — {timing}"
                            if food:
                                slot_str += f": {food}"
                            lines.append(slot_str)
                        else:
                            lines.append(f"  Slot {i}: {slot}")

                # supplement_schedule — ordered slot list
                if supplement_schedule := non_empty.get("supplement_schedule"):
                    lines.append("Supplements:")
                    for s in supplement_schedule:
                        if isinstance(s, dict):
                            slot = s.get("slot", "")
                            items = s.get("items") or []
                            item_str = ", ".join(str(i) for i in items) if items else str(s)
                            lines.append(f"  {slot}: {item_str}" if slot else f"  {item_str}")
                        else:
                            lines.append(f"  {s}")

                # plan_start_date — block anchor
                if plan_start_date := non_empty.get("plan_start_date"):
                    lines.append(f"Block anchor: {plan_start_date} (Block Week 1)")

                # Forward-compat fallback: any key not in _KNOWN_KEYS renders as "- k: v"
                for k, v in non_empty.items():
                    if k not in _KNOWN_KEYS:
                        lines.append(f"- {k}: {v}")

                training_profile_snippet = "\n".join(lines)

        coaching_guide_content = getattr(self, "_coaching_guide_content", "")
        return (
            template
            .replace("{coaching_guide}", coaching_guide_content)         # PHASE 22 — stable, first
            .replace("{self_md}", self._self_md_content)                 # stable — benefits from cache
            .replace("{self_state}", self_state_snippet)                 # volatile — after stable
            .replace("{journal_digest}", journal_digest)                 # Phase 17 — smart-only (D-15)
            .replace("{training_profile}", training_profile_snippet)     # PHASE 19 — PROMPT-01
            .replace("{today_date}", today_label)                        # dynamic — always last
        )

    def handle_message(
        self,
        user_message: str,
        user_id: int,
        photo_bytes: bytes | None = None,
        photo_mime_type: str | None = None,
    ) -> str:
        """Process one user message through the full dual-model pipeline.

        Args:
            user_message:    Raw text from the user interface.
            user_id:         Unique identifier for the user (Telegram ID or similar).
            photo_bytes:     Optional raw bytes of an attached photo.
            photo_mime_type: Optional MIME type of an attached photo.

        Returns:
            The agent's final response string, ready to send to the user.
        """
        # WHY: memory tools (remember/recall) need the user_id but the tool
        # dispatch signature does not pass it. A thread-local is safe here
        # because handle_message always runs in asyncio.to_thread — each call
        # gets its own thread from the pool.
        tool_registry.set_current_user_id(user_id)

        # Per D-03: SELF.md injected into smart_system only (not worker).
        smart_system = self.render_smart_system(self._smart_prompt_template)
        # Append the nutrition fueling-coach guidance (chat path only — the
        # autonomous/morning-briefing paths append it to their own composed
        # prompts, so doing it here rather than inside render_smart_system avoids
        # a double-append on those paths). Mirrors the cron append pattern.
        if self._meal_audit_content:
            smart_system = smart_system + "\n\n" + self._meal_audit_content
        worker_system = self._worker_prompt_template.replace("{today_date}", _today_israel())

        # Persist the incoming message and get the full history for this session.
        self.conversation_manager.append(user_id, "user", user_message)
        messages = self.conversation_manager.get(user_id)

        # Run the Smart Agent orchestration loop.
        if photo_bytes is not None:
            response_text = self._run_smart_loop(
                messages,
                smart_system,
                worker_system,
                photo_bytes=photo_bytes,
                photo_mime_type=photo_mime_type,
            )
        else:
            response_text = self._run_smart_loop(
                messages,
                smart_system,
                worker_system,
            )

        # Guard against an empty/whitespace-only reply (e.g. an LLM failure
        # path that yields ""). Without this, an empty assistant turn gets
        # persisted and the hub UI (which clears "Klaus is thinking..." as
        # soon as the last role is 'assistant') renders a blank bubble with
        # no error affordance and no retry (WR-05). Telegram callers get the
        # same fallback text their own except-path already uses.
        if not response_text or not response_text.strip():
            logger.warning(
                "handle_message: orchestrator produced an empty reply for user_id=%s",
                user_id,
            )
            response_text = (
                "Something went wrong on my end — give it another go in a moment."
            )

        # Persist the Smart Agent's final text response.
        self.conversation_manager.append(user_id, "assistant", response_text)
        return response_text

    # ------------------------------------------------------------------ #
    # Smart Agent loop (Gemini 3 Flash)                                   #
    # ------------------------------------------------------------------ #

    def _run_smart_loop(
        self,
        messages: list[dict],
        smart_system: str,
        worker_system: str,
        photo_bytes: bytes | None = None,
        photo_mime_type: str | None = None,
    ) -> str:
        """Run the Smart Agent tool-use loop until it produces a final text response.

        The Smart Agent may call delegate_to_worker one or more times. Each call is
        intercepted here and routed to _run_worker_loop(). Tool results are
        fed back to the Smart Agent so it can reason and respond.
        """
        # Work on a local deep copy so the conversation manager's history is not
        # polluted with intermediate tool_use / tool_result messages or large image data.
        import copy
        current_messages = copy.deepcopy(messages)

        # Inject the photo bytes as base64 into the last user message block if present.
        if photo_bytes and photo_mime_type and current_messages:
            last_msg = current_messages[-1]
            if last_msg.get("role") == "user":
                import base64
                photo_base64 = base64.b64encode(photo_bytes).decode("utf-8")
                user_content = last_msg.get("content")
                if isinstance(user_content, str):
                    last_msg["content"] = [
                        {"type": "text", "text": user_content},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": photo_mime_type,
                                "data": photo_base64,
                            }
                        }
                    ]

        # Extract last user message to see if we should include self-inspect schemas
        last_user_text = ""
        if messages:
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    content = msg.get("content")
                    if isinstance(content, str):
                        last_user_text = content
                    elif isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                last_user_text = block.get("text", "")
                    break

        smart_tools = tool_registry.get_smart_schemas(user_message=last_user_text)

        # Track the last substantive text produced by the brain alongside tool calls.
        # Used at loop exhaustion to suppress the apologetic double-send fallback when
        # the brain already produced a real answer (Phase 24 — double-send fix).
        last_response_text: str = ""

        for iteration in range(MAX_TOOL_ITERATIONS):
            try:
                response = self.smart_agent.chat(
                    current_messages,
                    system=smart_system,
                    tools=smart_tools,
                    purpose="smart",
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
                            tools=smart_tools,
                            purpose="smart_fallback",
                        )
                    except LLMError as fallback_exc:
                        logger.error(

                            "Smart agent FALLBACK also failed (iter %d): %s",
                            iteration, fallback_exc,
                        )
                        return CONNECTIVITY_ERROR_TEXT
                else:
                    return CONNECTIVITY_ERROR_TEXT

            tool_calls = response["tool_calls"]
            response_text = response["text"]

            # Track the last substantive text produced (for exhaustion double-send fix).
            if response_text:
                last_response_text = response_text

            # No tool calls → Smart Agent has produced its final response.
            if not tool_calls:
                return response_text or ""

            # Build the full assistant message content block (text + tool_use blocks).
            # WHY: Anthropic requires the complete assistant message (including any
            # intermediate text) before the corresponding tool_result messages.
            assistant_content: list[dict] = []
            if response_text:
                text_block = {"type": "text", "text": response_text}
                if response.get("thought_signature"):
                    text_block["thought_signature"] = response["thought_signature"]
                assistant_content.append(text_block)
            for tc in tool_calls:
                tc_block = {
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": tc["input"],
                }
                if tc.get("thought_signature"):
                    tc_block["thought_signature"] = tc["thought_signature"]
                assistant_content.append(tc_block)
            
            assistant_msg = {"role": "assistant", "content": assistant_content}
            if response.get("reasoning_content"):
                assistant_msg["reasoning_content"] = response["reasoning_content"]
            current_messages.append(assistant_msg)

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
                        # Path B: Flash solo — return immediately, no Smart Agent review.
                        logger.info("Path B delegation: returning Flash response directly.")
                        return worker_response

                    # Path A: feed Flash's result back to the Smart Agent for review + crafting.
                    logger.info("Path A delegation: returning Flash result to the Smart Agent.")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": worker_response,
                    })

                else:
                    # WHY: remember/recall are always called directly by the Smart Agent —
                    # they require the Smart Agent's judgment and must not go via the worker.
                    # Any other direct tool call is unexpected; log a warning.
                    if tool_name not in tool_registry.SMART_AGENT_DIRECT_TOOLS:
                        logger.warning(
                            "Smart Agent called tool '%s' directly (expected delegation).", tool_name
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
            # grouping them avoids unnecessary turn-counting against the Smart Agent's context.
            if tool_results:
                current_messages.append({"role": "user", "content": tool_results})

        logger.error(
            "Smart loop exceeded MAX_TOOL_ITERATIONS (%d) without a final text response.",
            MAX_TOOL_ITERATIONS,
        )
        # Double-send fix (Phase 24): when the brain produced a substantive answer
        # alongside its final tool calls, return that answer directly instead of
        # discarding it and emitting the apologetic fallback. The >100-char guard
        # avoids returning trivially short fragments (e.g., "Understood." or "").
        # Anti-fabrication SC-1 holds — the returned text was composed by the brain,
        # not synthesized here. The sentinel string below is left intact so that
        # tests/test_autonomous.py::test_sentinel_substring_matches_main_constant
        # and the D-19 fallback detection in autonomous.py continue to work.
        if last_response_text and len(last_response_text) > 100:
            logger.warning(
                "Returning last substantive brain response (%d chars) instead of "
                "apologetic fallback to suppress double-send.",
                len(last_response_text),
            )
            return last_response_text
        return (
            "That one took more steps than I expected to work through — "
            "try rephrasing it or breaking it into smaller parts."
        )

    # ------------------------------------------------------------------ #
    # Worker Agent loop (Gemini Flash)                                   #
    # ------------------------------------------------------------------ #

    def _run_worker_loop(self, task: str, worker_system: str) -> str:
        """Run Gemini Flash on a delegated task, managing its own tool-use loop.

        Args:
            task: Natural language instruction from the Smart Agent.
            worker_system: Rendered worker system prompt with today's date.

        Returns:
            Flash's final text response (fed back to the Smart Agent, or returned directly).
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
                    purpose="worker",
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
            
            worker_assistant_msg = {"role": "assistant", "content": worker_assistant_content}
            if response.get("reasoning_content"):
                worker_assistant_msg["reasoning_content"] = response["reasoning_content"]
            worker_messages.append(worker_assistant_msg)

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
    """Load a prompt file relative to the project root (cached per process).

    Thin delegate to :func:`core.prompt_loader.load_prompt` — kept under the
    original name because callers and tests reference it directly.

    Raises:
        FileNotFoundError: If the prompt file does not exist.
    """
    return prompt_loader.load_prompt(relative_path)


def _load_self_md() -> str:
    """Read docs/SELF.md from disk. Returns empty string if file absent.

    Called once at startup; the result is stored on the orchestrator and
    injected into every smart_system prompt without further file I/O.
    """
    root = Path(__file__).resolve().parent.parent
    self_md_path = root / "docs" / "SELF.md"
    try:
        return self_md_path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("SELF.md not found at %s — self-knowledge injection disabled", self_md_path)
        return ""


def _load_coaching_guide_slim() -> str:
    """Read the slim core digest block from docs/COACHING_GUIDE.md.

    Extracts only the content between <!-- SLIM_CORE_START --> and
    <!-- SLIM_CORE_END --> markers. Returns empty string if file absent
    or markers not found. Called once at startup; stored on orchestrator.
    Per D-04: only the slim core (~200-300 lines) is injected as a
    stable cached prefix. Full guide is read on-demand by read_coaching_guide().
    """
    import re as _re
    root = Path(__file__).resolve().parent.parent
    guide_path = root / "docs" / "COACHING_GUIDE.md"
    try:
        content = guide_path.read_text(encoding="utf-8")
    except OSError:
        logger.warning(
            "COACHING_GUIDE.md not found at %s — coaching knowledge injection disabled",
            guide_path,
        )
        return ""
    # Extract slim core block between markers
    m = _re.search(
        r"<!-- SLIM_CORE_START -->(.*?)<!-- SLIM_CORE_END -->",
        content,
        _re.DOTALL,
    )
    if not m:
        logger.warning(
            "COACHING_GUIDE.md: <!-- SLIM_CORE_START/END --> markers not found — "
            "returning empty coaching injection"
        )
        return ""
    slim = m.group(1).strip()
    # Size contract (two-tier, phase-22 WR-03):
    #   - ADVISORY early-warning at 10k chars — logs but does not alter content.
    #     Runtime truncation is deliberately avoided: chopping the block would drop
    #     coaching content mid-section, which is worse than an over-long prefix.
    #   - HARD ceiling (15k chars / 350 lines) is enforced at build time by
    #     test_load_coaching_guide_slim_size_guard against the committed guide, so an
    #     oversized slim core fails CI before it can ship.
    if len(slim) > 10_000:
        logger.warning(
            "COACHING_GUIDE.md slim core is %d chars — over the 10k advisory threshold "
            "(expected ~4000; hard ceiling 15000 enforced by tests). "
            "Check SLIM_CORE_START/END markers.",
            len(slim),
        )
    return slim


def _extract_intro_paragraph(self_md_content: str) -> str:
    """Extract the first non-empty paragraph from SELF.md for use as identity_summary.

    Skips the front-matter block (--- ... ---), the H1 heading, the sha comment,
    and the generated-by note. Returns the first paragraph of substantive prose.
    Returns a default string if no paragraph is found.
    """
    lines = self_md_content.splitlines()
    in_front_matter = False
    past_front_matter = False
    paragraph_lines: list[str] = []
    collecting = False

    for line in lines:
        stripped = line.strip()
        if stripped == "---" and not past_front_matter:
            in_front_matter = not in_front_matter
            if not in_front_matter:
                past_front_matter = True
            continue
        if in_front_matter:
            continue
        # Skip headings, comments, blockquotes, empty lines before paragraph starts
        if stripped.startswith("#") or stripped.startswith("<!--") or stripped.startswith(">"):
            continue
        if not stripped and not collecting:
            continue
        if stripped and not collecting:
            collecting = True
        if collecting:
            if not stripped:
                break  # End of first paragraph
            paragraph_lines.append(line)

    result = " ".join(paragraph_lines).strip()
    return result or "Klaus is a personal AI agent deployed on Cloud Run."


def _build_self_state_store() -> SelfStateStore | None:
    """Build a SelfStateStore from environment variables.

    Returns None if GCP_PROJECT_ID is not set (e.g. local dev without env).
    """
    project_id = os.environ.get("GCP_PROJECT_ID")
    if not project_id:
        logger.warning("GCP_PROJECT_ID not set — SelfStateStore disabled")
        return None
    database = os.environ.get("FIRESTORE_DATABASE", "(default)")
    return SelfStateStore(project_id=project_id, database=database)


def _build_journal_store() -> JournalStore | None:
    """Build a JournalStore from environment variables.

    Returns None if GCP_PROJECT_ID is not set (e.g. local dev without env).
    """
    project_id = os.environ.get("GCP_PROJECT_ID")
    if not project_id:
        logger.warning("GCP_PROJECT_ID not set — JournalStore disabled")
        return None
    database = os.environ.get("FIRESTORE_DATABASE", "(default)")
    return JournalStore(project_id=project_id, database=database)


def _build_user_profile_store() -> UserProfileStore | None:
    """Build a UserProfileStore from environment variables (Phase 19 Plan 02).

    Returns None if GCP_PROJECT_ID is not set (e.g. local dev without env)
    or if construction fails for any reason — bootstrap is best-effort and
    must never block AgentOrchestrator startup (Pitfall 7).
    """
    project_id = os.environ.get("GCP_PROJECT_ID")
    if not project_id:
        logger.warning("GCP_PROJECT_ID not set — UserProfileStore disabled")
        return None
    try:
        database = os.environ.get("FIRESTORE_DATABASE", "(default)")
        return UserProfileStore(project_id=project_id, database=database)
    except Exception:
        logger.warning("Failed to build UserProfileStore", exc_info=True)
        return None


def _today_israel() -> str:
    """Return today's date in Israel time as a human-readable string.

    Example: 'Sunday, May 4, 2025'
    """
    now = datetime.now(tz=ISRAEL_TZ)
    return f"{now.strftime('%A')}, {now.strftime('%B')} {now.day}, {now.year}"
