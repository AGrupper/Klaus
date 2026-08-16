# Groq Tick-Efficiency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring every tick-brain Groq request safely under the 8,000-tokens/request TPM ceiling and cut daily consumption well under the 200K/day cap, with zero loss to Klaus's judgment.

**Architecture:** Three code levers on the always-on tick path — (1) cheaper Groq calls via a new `reasoning_effort` passthrough + a measured, lowered `max_tokens` + conditional heavy-context rendering, (2) fewer calls via a fail-open change-detection skip gate, and (3) a recalibrated CI token-budget guard that can no longer false-pass. The paid brain and the fallback contract are untouched.

**Tech Stack:** Python 3.13 (prod Dockerfile 3.11), Firestore (`klaus-firestore`), Groq OpenAI-compat (`openai/gpt-oss-120b`), pytest (per-file), tiktoken `o200k_harmony`.

## Global Constraints

- Per-request invariant: `input_tokens + max_tokens < 8000` for every tick-brain Groq call; design target **≤ 7,200**.
- Per-day invariant: successful Groq `in+out` tokens/day `< 200,000`; target ≤ ~130K.
- Context-only invariant (MEM-05): `conversation_tail`, `training_reality`, `standing_directives`, `location` must never flip an empty tick to non-empty and must be **excluded** from the change-detection signature.
- Fail-open: every new store read/lookup degrades to "proceed with the normal call" on error; never blocks or crashes a tick.
- Judgment parity: no change may convert a real `should_act=True` into false silence (rules out blind `max_tokens` truncation — hence `reasoning_effort=low` + measurement).
- Firestore database name is `klaus-firestore` (never `(default)` for real reads); all resource names lowercase `klaus-`.
- `load_dotenv(override=True)` everywhere; venv Python 3.13 (or 3.11), never 3.14.
- Tests run per-file: `.venv/bin/python -m pytest <file> -q` (full-suite segfaults on Py3.13 — known env quirk). Baseline must stay green.
- Commit trailer on every commit:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

---

### Task 1: `extra_params` passthrough + truncation `stop_reason` in LLMClient

**Files:**
- Modify: `core/llm_client.py` (public `LLMClient.chat` ~98-144; `_BaseBackend.chat` ~186-191; `_AnthropicBackend.chat` ~210-214; `_OpenAIBackend.chat` ~631-689; Gemini backend `chat` ~381-395)
- Test: `tests/test_llm_client.py`

**Interfaces:**
- Produces: `LLMClient.chat(..., extra_params: dict | None = None)` — on the OpenAI-compat backend, keys in `extra_params` are merged into `client.chat.completions.create(**kwargs)` (e.g. `{"reasoning_effort": "low"}`). Anthropic/Gemini backends accept the kwarg and ignore it.
- Produces: `_OpenAIBackend.chat` returns `stop_reason == "max_tokens"` when the OpenAI `finish_reason == "length"` (was previously only `"tool_use"`/`"end_turn"`).

- [ ] **Step 1: Write the failing test — extra_params merged on openai, ignored elsewhere**

Add to `tests/test_llm_client.py` (follow the file's existing mock style for `client.chat.completions.create`):

```python
def test_extra_params_forwarded_on_openai_backend(monkeypatch):
    """extra_params (e.g. reasoning_effort) reach the OpenAI create() call."""
    from core.llm_client import LLMClient
    captured = {}

    class _FakeUsage:
        prompt_tokens = 10
        completion_tokens = 5

    class _FakeMsg:
        content = '{"should_act": false, "reason": "quiet"}'
        tool_calls = None
        reasoning_content = None

    class _FakeChoice:
        message = _FakeMsg()
        finish_reason = "stop"

    class _FakeResp:
        choices = [_FakeChoice()]
        usage = _FakeUsage()

    client = LLMClient(backend="openai", model="openai/gpt-oss-120b",
                       api_key="k", base_url="https://api.groq.com/openai/v1")

    def _fake_create(**kwargs):
        captured.update(kwargs)
        return _FakeResp()

    monkeypatch.setattr(client._impl.client.chat.completions, "create", _fake_create)

    client.chat([{"role": "user", "content": "hi"}],
                extra_params={"reasoning_effort": "low"})

    assert captured.get("reasoning_effort") == "low"


def test_extra_params_ignored_on_gemini_backend(monkeypatch):
    """Non-openai backends accept extra_params without passing it through / erroring."""
    from core.llm_client import LLMClient
    # Build a gemini client with its generate call stubbed to a minimal shape.
    # (Mirror the existing gemini mock helper in this test module.)
    client = LLMClient(backend="gemini", model="gemini-3.5-flash", api_key="k")
    # Should not raise even though gemini has no reasoning_effort concept.
    # Use the module's existing gemini-response monkeypatch helper here.
    # Assert the call returns a dict envelope.
    # (Reuse whatever fixture the file already uses for gemini responses.)
```

> Note for implementer: `tests/test_llm_client.py` already has gemini/anthropic mock scaffolding (32 tests). Reuse the existing helpers for the gemini case rather than hand-rolling a new stub; the assertion is simply "does not raise and returns an envelope dict."

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_llm_client.py::test_extra_params_forwarded_on_openai_backend -q`
Expected: FAIL — `chat()` has no `extra_params` parameter (TypeError).

- [ ] **Step 3: Add `extra_params` to the public `chat` signature and thread it**

In `core/llm_client.py`, public `LLMClient.chat` (~line 98-103), add the param and pass it to `_impl.chat`:

```python
    def chat(self, messages: list[dict], *, system: str | tuple[str, str] | None = None,
             tools: list[dict] | None = None,
             purpose: str = "",
             max_tokens: int | None = None,
             temperature: float | None = None,
             extra_params: dict | None = None,
             on_text_delta: Callable[[str], None] | None = None) -> dict:
```

Update the `_impl.chat(...)` call (~line 142-144) to forward it:

```python
        result = self._impl.chat(messages, system=system, tools=tools,
                                 max_tokens=max_tokens, temperature=temperature,
                                 extra_params=extra_params,
                                 on_text_delta=on_text_delta)
```

- [ ] **Step 4: Add `extra_params` to `_BaseBackend.chat` and all three backends**

`_BaseBackend.chat` (~186): add `extra_params: dict | None = None,` to the signature.

`_AnthropicBackend.chat` (~210) and the Gemini backend `chat` (~381): add `extra_params: dict | None = None,` to the signature and **do not use it** (documented ignore — Anthropic/Gemini have no such param; adding it would 400).

`_OpenAIBackend.chat` (~631): add `extra_params: dict | None = None,` to the signature; merge it into `kwargs` just before the `create` call and map the truncation finish reason:

```python
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": openai_messages,
            "max_tokens": max_tokens or MAX_TOKENS,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if openai_tools:
            kwargs["tools"] = openai_tools
        if extra_params:
            # Backend-specific knobs (e.g. Groq's reasoning_effort). Merged
            # last but never allowed to clobber the core call shape.
            for k, v in extra_params.items():
                if k not in ("model", "messages", "max_tokens", "tools"):
                    kwargs[k] = v
```

And where `stop_reason` is computed (~678), account for truncation:

```python
        finish_reason = getattr(choice, "finish_reason", None)
        if tool_calls:
            stop_reason = "tool_use"
        elif finish_reason == "length":
            stop_reason = "max_tokens"
        else:
            stop_reason = "end_turn"
```

- [ ] **Step 5: Write the failing test — truncation surfaces as stop_reason max_tokens**

```python
def test_openai_length_finish_maps_to_max_tokens_stop(monkeypatch):
    from core.llm_client import LLMClient

    class _U: prompt_tokens = 10; completion_tokens = 2048
    class _M: content = "<think>..."; tool_calls = None; reasoning_content = None
    class _C: message = _M(); finish_reason = "length"
    class _R: choices = [_C()]; usage = _U()

    client = LLMClient(backend="openai", model="openai/gpt-oss-120b",
                       api_key="k", base_url="https://api.groq.com/openai/v1")
    monkeypatch.setattr(client._impl.client.chat.completions, "create",
                        lambda **kw: _R())
    out = client.chat([{"role": "user", "content": "hi"}])
    assert out["stop_reason"] == "max_tokens"
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_llm_client.py -q`
Expected: PASS (34 prior + 3 new = 37).

- [ ] **Step 7: Commit**

```bash
git add core/llm_client.py tests/test_llm_client.py
git commit -m "feat(groq): extra_params passthrough + truncation stop_reason in LLMClient"
```

---

### Task 2: tick-brain `reasoning_effort=low`, lowered `max_tokens`, truncation warning

**Files:**
- Modify: `core/tick_brain.py` (`_DEFAULT_MAX_TOKENS` constant; `think()` primary call ~239-247; after-success/after-parse for truncation warn)
- Test: `tests/test_tick_brain.py`

**Interfaces:**
- Consumes: `LLMClient.chat(..., extra_params=...)` from Task 1.
- Produces: primary Groq triage call sends `extra_params={"reasoning_effort": "low"}`; fallback path does **not**. New `_DEFAULT_MAX_TOKENS` value (measured; see Step 1).

- [ ] **Step 1: Measure gpt-oss triage completion size (one-off, informs the constant)**

Run a controlled Groq call with `reasoning_effort=low` on the maximal fixture to read actual `out_tokens` and `stop_reason` (gpt-oss never succeeds in prod today, so this is the first real number):

```bash
cd /Users/amitgrupper/Desktop/Klaus
.venv/bin/python -c "
import os; from datetime import datetime; from zoneinfo import ZoneInfo
os.environ.setdefault('GCP_PROJECT_ID','klaus-agent')
from core.llm_client import LLMClient
import core.autonomous as A
from tests.test_token_budget import _build_maximal_fixture_situation
now = datetime(2026,7,27,8,0,tzinfo=ZoneInfo('Asia/Jerusalem'))
sys_ = A._load_prompt('prompts/autonomous_triage.md')
user = A._build_triage_prompt(_build_maximal_fixture_situation(now), sys_)
c = LLMClient(backend='openai', model='openai/gpt-oss-120b',
              api_key=os.environ['TICK_BRAIN_API_KEY'],
              base_url='https://api.groq.com/openai/v1')
r = c.chat([{'role':'user','content':user}], system=sys_, max_tokens=2048,
           temperature=0.6, extra_params={'reasoning_effort':'low'})
print('out_tokens=', r['usage']['out_tokens'], 'stop=', r['stop_reason'])
print(r['text'][:200])
" 2>&1 | tail -5
```

Record the number. Set `_DEFAULT_MAX_TOKENS = max(measured_out_tokens_p95, 768) rounded up to the next 128` — expected **~1024**. If the measurement can't run (no local `TICK_BRAIN_API_KEY`), default to **1024** (input ~6,100 + 1024 = 7,124 < 8,000) and rely on the Step-4 truncation warning + guard to catch under-sizing. Document the chosen value + evidence in the commit body.

- [ ] **Step 2: Write the failing test — reasoning_effort on primary only**

Add to `tests/test_tick_brain.py` (reuse the file's existing `_FakeClient`/monkeypatch style):

```python
def test_think_sends_reasoning_effort_low_on_primary_not_fallback(monkeypatch):
    """Primary Groq call carries reasoning_effort=low; fallback does not."""
    from core.tick_brain import TickBrain
    calls = []

    class _Client:
        def __init__(self, primary): self.primary = primary
        def chat(self, messages, **kw):
            calls.append(("primary" if self.primary else "fallback", kw.get("extra_params")))
            if self.primary:
                from core.llm_client import LLMError
                raise LLMError("boom", backend="openai", status_code=413)
            return {"text": '{"should_act": false, "reason": "x"}',
                    "usage": {"in_tokens": 1, "out_tokens": 1}, "stop_reason": "end_turn"}

    tb = TickBrain.__new__(TickBrain)
    tb._client = _Client(primary=True)
    tb._fallback_client = _Client(primary=False)
    tb._max_tokens = 1024; tb._temperature = 0.6
    tb._model = "openai/gpt-oss-120b"; tb._fallback_model = "gemini-3.5-flash"

    tb.think("situation")

    primary = next(c for c in calls if c[0] == "primary")
    fallback = next(c for c in calls if c[0] == "fallback")
    assert primary[1] == {"reasoning_effort": "low"}
    assert not fallback[1]  # None or {}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_tick_brain.py::test_think_sends_reasoning_effort_low_on_primary_not_fallback -q`
Expected: FAIL — primary call has no `extra_params`.

- [ ] **Step 4: Implement — thread reasoning_effort, lower default, warn on truncation**

In `core/tick_brain.py`: set the new default (value from Step 1):

```python
_DEFAULT_MAX_TOKENS = 1024   # was 2048 — keeps input(~6.1K)+max_tokens under Groq's 8K TPM/request ceiling (measured 2026-07-27)
```

In `think()`, the primary call (~239-247) adds `extra_params`:

```python
                response = self._client.chat(
                    messages,
                    system=active_system,
                    tools=tools,
                    purpose=primary_purpose,
                    max_tokens=self._max_tokens,
                    temperature=self._temperature,
                    extra_params={"reasoning_effort": "low"},
                )
```

After the primary succeeds (in the `else:` block after the ledger increment, ~266), add a truncation warning:

```python
                if response.get("stop_reason") == "max_tokens":
                    logger.warning(
                        "tick-brain: triage truncated at max_tokens=%d — verdict may "
                        "be degraded; consider raising TICK_BRAIN_MAX_TOKENS",
                        self._max_tokens,
                    )
```

Leave the fallback call (~275) unchanged (no `extra_params` — Gemini ignores it anyway, kept clean).

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_tick_brain.py -q`
Expected: PASS (all prior + 1 new).

- [ ] **Step 6: Commit**

```bash
git add core/tick_brain.py tests/test_tick_brain.py
git commit -m "feat(groq): reasoning_effort=low + max_tokens 2048->1024 + truncation warn on tick-brain"
```

---

### Task 3: Recalibrate the MEM-05 token-budget guard

**Files:**
- Modify: `tests/test_token_budget.py` (`_build_maximal_fixture_situation` sizes; `_GROQ_REQUEST_TOKEN_CEILING`; assertion)

**Interfaces:**
- Consumes: new `_DEFAULT_MAX_TOKENS` (1024) from Task 2 (already imported at line 38).

**Why:** Production requests land at ~8,150 while this guard passed at 7,730 — its fixture under-measures real mornings by ~420 tokens and asserts `≤ 8000` with zero margin. Enlarge the fixture to real worst-case and assert `≤ 7200` (an 800-token TPM safety margin).

- [ ] **Step 1: Tighten the ceiling to a margin target**

Change the constant (line ~42-43) and add a design-margin constant:

```python
# Groq's verified free-tier per-request ceiling for openai/gpt-oss-120b.
_GROQ_REQUEST_TOKEN_CEILING = 8000
# Design target: leave >=800 tokens of TPM headroom below the hard ceiling so a
# busier-than-fixture day (or a same-minute heartbeat+autonomous collision)
# does not 413. Production requests hit ~8,150 at the old max_tokens=2048; this
# margin + the lowered max_tokens is what keeps every request admissible.
_GROQ_REQUEST_TOKEN_TARGET = 7200
```

- [ ] **Step 2: Enlarge the fixture to real worst-case**

In `_build_maximal_fixture_situation`, raise the busy-day sizes so `system+user` reflects a genuine packed morning (~6,100 input, matching the observed production `Requested - max_tokens`). Concretely bump the calendar range and overdue list:

```python
        for i in range(12)  # packed real morning (was 7) — real prod input ~6.1K
    ]
    ticktick_overdue = [
        {"title": f"Overdue task #{i} — reply / ship / follow up", "due": "2026-07-15"}
        for i in range(6)  # was 3
    ]
```

(Keep the capped blocks — `conversation_tail` 15×240, `training_reality` 5 dates — as-is; they are the render-capped worst case already.)

- [ ] **Step 3: Update the assertion to the target**

```python
    total = system_tokens + user_tokens + _TICK_BRAIN_MAX_TOKENS

    assert total <= _GROQ_REQUEST_TOKEN_TARGET, (
        f"maximal triage prompt+completion budget {total} tokens "
        f"(system={system_tokens}, user={user_tokens}, "
        f"completion={_TICK_BRAIN_MAX_TOKENS}) exceeds the {_GROQ_REQUEST_TOKEN_TARGET}-"
        f"token design target (hard Groq ceiling {_GROQ_REQUEST_TOKEN_CEILING}) for "
        "openai/gpt-oss-120b — reduce max_tokens or cap the triage render"
    )
```

- [ ] **Step 4: Run — expect it to reveal the real state, then converge**

Run: `.venv/bin/python -m pytest tests/test_token_budget.py -q`
Expected: With `_DEFAULT_MAX_TOKENS=1024` and the enlarged fixture, `total ≈ 6100 + 1024 = 7124 ≤ 7200` → PASS. **If it FAILS** (fixture input larger than 6,176), that is the guard doing its job — proceed to Task 4 (conditional render + caps) which reduces the rendered input, then re-run this test until green. Do not relax the target to make it pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_token_budget.py
git commit -m "test(groq): recalibrate MEM-05 guard to real worst-case + 7200 target (fixes false-pass)"
```

---

### Task 4: Conditional heavy-context rendering in `_build_triage_prompt`

**Files:**
- Modify: `core/autonomous.py` (`_build_triage_prompt` ~1164-1215 and the Phase-32 render section that follows it)
- Test: `tests/test_autonomous.py`

**Interfaces:**
- Produces: `_build_triage_prompt` omits the `training_reality` block on days with no planned/logged session, and the `conversation_tail` block when there is no genuinely recent exchange; the maximal (all-present) render still fits Task 3's guard.

- [ ] **Step 1: Write the failing tests — omission when not salient, inclusion when salient**

Add to `tests/test_autonomous.py`:

```python
def test_triage_prompt_omits_training_reality_on_no_session_day():
    import core.autonomous as A
    sys_ = A._load_prompt("prompts/autonomous_triage.md")
    from datetime import datetime; from zoneinfo import ZoneInfo
    now = datetime(2026, 7, 27, 8, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))
    situ = {"now_context": A._now_context(now), "calendar": [], "ticktick_overdue": [],
            "hours_since_contact": 5.0, "training_reality": {}, "conversation_tail": []}
    prompt = A._build_triage_prompt(situ, sys_)
    assert "training_reality" not in prompt.lower().replace(" ", "_") or "training reality" not in prompt.lower()


def test_triage_prompt_includes_training_reality_when_session_present():
    import core.autonomous as A
    from datetime import datetime; from zoneinfo import ZoneInfo
    now = datetime(2026, 7, 27, 8, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))
    today = now.date().isoformat()
    situ = {"now_context": A._now_context(now), "calendar": [], "ticktick_overdue": [],
            "hours_since_contact": 5.0,
            "training_reality": {today: {"slots": {"am": "planned", "pm": "planned"}}},
            "conversation_tail": []}
    sys_ = A._load_prompt("prompts/autonomous_triage.md")
    prompt = A._build_triage_prompt(situ, sys_)
    assert today in prompt  # the reality block for today is rendered
```

> Implementer: read the exact Phase-32 render helpers (`_render_training_reality_tight`, `_render_conversation_tail_tight`) that Plan 32-07 added below `_build_triage_prompt`, and match the real block markers/headings for the assertions. Adjust the assertion strings to the actual rendered header text.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_autonomous.py -k "training_reality" -q`
Expected: FAIL — training_reality is always rendered.

- [ ] **Step 3: Implement salience gating in the render**

In `_build_triage_prompt`, wrap the two Phase-32 render calls in salience checks (a rest/quiet day contributes no heavy block):

```python
    # MEM-05 efficiency: render the heavy Phase-32 blocks only when salient, so
    # ordinary/quiet ticks send a lean prompt (keeps input well under Groq's 8K
    # TPM/request ceiling; the maximal all-present case still fits the guard).
    training_reality = situation.get("training_reality") or {}
    today_iso = now_context_date  # derive from now_context / situation
    _has_session = any(
        (v or {}).get("slots") and any(s not in (None, "", "rest") for s in (v["slots"].values()))
        for v in training_reality.values()
    )
    training_reality_block = (
        _render_training_reality_tight(training_reality) if _has_session else ""
    )

    conversation_tail = situation.get("conversation_tail") or []
    conversation_tail_block = (
        _render_conversation_tail_tight(conversation_tail) if conversation_tail else ""
    )
```

Then include `training_reality_block` / `conversation_tail_block` in the final prompt string only when non-empty (drop the label lines entirely when empty rather than printing an empty section).

> Implementer: `now_context_date` — reuse the date already available in `_build_triage_prompt` (from `situation["now_context"]`); do not call `datetime.now()`.

- [ ] **Step 4: Run the render tests + guard**

Run: `.venv/bin/python -m pytest tests/test_autonomous.py -k "training_reality or conversation_tail or triage" tests/test_token_budget.py -q`
Expected: PASS. If the guard (Task 3) was still red, it should now be green (lean render trims worst-case input).

- [ ] **Step 5: Commit**

```bash
git add core/autonomous.py tests/test_autonomous.py
git commit -m "feat(groq): render training_reality/conversation_tail only when salient (lean triage)"
```

---

### Task 5: `TickSignatureStore` — persist the last salient-signal signature

**Files:**
- Modify: `memory/firestore_db.py` (new store class, place adjacent to `GroqTokenLedgerStore` ~2275)
- Test: `tests/test_firestore_db.py`

**Interfaces:**
- Produces: `TickSignatureStore(project_id, database)` with `.get() -> str | None` (never raises → None on error) and `.set(signature: str) -> None` (never raises).

- [ ] **Step 1: Write the failing test (mock the firestore client like the ledger tests do)**

Add to `tests/test_firestore_db.py` (mirror the `GroqTokenLedgerStore` test setup in that file):

```python
def test_tick_signature_store_roundtrip(monkeypatch):
    from memory.firestore_db import TickSignatureStore
    # Reuse the file's existing fake-firestore fixture used for GroqTokenLedgerStore.
    store = TickSignatureStore(project_id="klaus-agent", database="klaus-firestore")
    assert store.get() is None          # absent -> None
    store.set("abc123")
    assert store.get() == "abc123"


def test_tick_signature_store_fails_open(monkeypatch):
    from memory.firestore_db import TickSignatureStore
    store = TickSignatureStore(project_id="klaus-agent", database="klaus-firestore")
    # Force the underlying doc read to raise; get() must swallow and return None.
    monkeypatch.setattr(store._col, "document", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert store.get() is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_firestore_db.py -k tick_signature -q`
Expected: FAIL — `TickSignatureStore` does not exist.

- [ ] **Step 3: Implement the store (mirrors GroqTokenLedgerStore idioms)**

Add to `memory/firestore_db.py`:

```python
class TickSignatureStore:
    """Last salient-signal signature for the autonomous tick (change-detection).

    Firestore collection: tick_signature (lowercase per project casing invariant).
    Single document per user ("amit") holding the hash of the last tick's salient
    trigger signals. Used to skip the Groq triage call when nothing material has
    changed since the previous tick — a $0 pre-Groq gate. Never raises: a read
    error returns None (→ proceed with the call), a write error is swallowed
    (→ next tick simply re-evaluates). Fail-open by construction.
    """

    _COLLECTION = "tick_signature"
    _DOC_ID = "amit"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def get(self) -> str | None:
        try:
            snap = self._col.document(self._DOC_ID).get()
            if not snap.exists:
                return None
            return (snap.to_dict() or {}).get("signature")
        except Exception:
            logger.warning("TickSignatureStore.get() failed", exc_info=True)
            return None

    def set(self, signature: str) -> None:
        try:
            from datetime import datetime, timezone
            self._col.document(self._DOC_ID).set(
                {"signature": signature, "updated_at": datetime.now(timezone.utc).isoformat()},
                merge=True,
            )
        except Exception:
            logger.warning("TickSignatureStore.set() failed", exc_info=True)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_firestore_db.py -k tick_signature -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add memory/firestore_db.py tests/test_firestore_db.py
git commit -m "feat(groq): TickSignatureStore for tick change-detection (fail-open)"
```

---

### Task 6: Signature computation + change-detection gate in `run_autonomous_tick`

**Files:**
- Modify: `core/autonomous.py` (new `_compute_signal_signature`; gate insertion in `run_autonomous_tick` ~1718, after the follow-up block, before Layer-1 triage)
- Test: `tests/test_autonomous.py`

**Interfaces:**
- Consumes: `TickSignatureStore` (Task 5).
- Produces: `_compute_signal_signature(situation: dict) -> str` — a stable hash over ONLY salient trigger fields; context-only fields excluded.

- [ ] **Step 1: Write failing tests — signature stability + gate skip**

```python
def test_signature_stable_and_excludes_context_only_fields():
    import core.autonomous as A
    base = {"ticktick_overdue": [{"title": "x", "due": "2026-07-15"}],
            "due_followups": [], "calendar": [], "now_context": {"hour": 8},
            "meals_since_last_tick": [], "habit_pending": [], "recovery": {},
            "hours_since_contact": 5.0}
    sig1 = A._compute_signal_signature(base)
    # Changing ONLY a context-only field must NOT change the signature.
    ctx = dict(base, training_reality={"2026-07-27": {"slots": {"am": "done"}}},
               conversation_tail=[{"role": "user", "content": "hi"}],
               standing_directives=[{"id": "d1"}], location={"city": "Paris"})
    assert A._compute_signal_signature(ctx) == sig1
    # Changing a trigger field MUST change it.
    changed = dict(base, ticktick_overdue=[])
    assert A._compute_signal_signature(changed) != sig1


def test_silence_bucket_not_raw_hours():
    import core.autonomous as A
    a = {"ticktick_overdue": [], "due_followups": [], "calendar": [],
         "now_context": {"hour": 8}, "meals_since_last_tick": [], "habit_pending": [],
         "recovery": {}, "hours_since_contact": 3.0}
    b = dict(a, hours_since_contact=3.5)   # same silence bucket (both below threshold)
    assert A._compute_signal_signature(a) == A._compute_signal_signature(b)


def test_tick_skips_groq_when_signature_unchanged(monkeypatch):
    """Non-empty but unchanged signals → skip triage, return silence."""
    import core.autonomous as A
    import asyncio

    situation = {"empty": False, "due_followups": [],
                 "ticktick_overdue": [{"title": "x", "due": "2026-07-15"}],
                 "calendar": [], "now_context": {"hour": 8, "tick_index": 3},
                 "meals_since_last_tick": [], "habit_pending": [], "recovery": {},
                 "hours_since_contact": 5.0}
    monkeypatch.setattr(A, "gather_situation", lambda now: situation)

    class _Sig:
        def get(self): return A._compute_signal_signature(situation)  # already-seen
        def set(self, s): pass
    monkeypatch.setattr(A, "_tick_signature_store", lambda: _Sig())

    # If triage were called it would raise — proving it is skipped.
    def _boom(*a, **k): raise AssertionError("tick-brain must not be called when unchanged")
    monkeypatch.setattr("core.tick_brain.TickBrain", _boom)
    monkeypatch.setattr(A, "_write_tick_log", lambda *a, **k: asyncio.sleep(0))

    decision = asyncio.get_event_loop().run_until_complete(A.run_autonomous_tick(bot=None))
    assert any("signals_unchanged" in str(t) for t in decision["trail"])
    assert decision["sent"] is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_autonomous.py -k "signature or silence_bucket or unchanged" -q`
Expected: FAIL — `_compute_signal_signature` / `_tick_signature_store` not defined.

- [ ] **Step 3: Implement the signature helper + store accessor**

Add near the other module helpers in `core/autonomous.py`:

```python
import hashlib as _hashlib

def _tick_signature_store():
    """Lazy accessor for TickSignatureStore (mirrors other store accessors)."""
    from memory.firestore_db import TickSignatureStore
    return TickSignatureStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )

def _compute_signal_signature(situation: dict) -> str:
    """Stable hash over ONLY the salient TRIGGER signals (the exact set
    _is_empty_signals keys on). Context-only signals (conversation_tail,
    training_reality, standing_directives, location) are deliberately EXCLUDED
    (MEM-05 invariant): a change in them alone must not force a paid re-eval.
    hours_since_contact is reduced to its silence BUCKET (bool over the trigger
    threshold), never the raw float — otherwise it changes every tick and the
    gate never fires.
    """
    hsc = situation.get("hours_since_contact")
    silence_bucket = bool(isinstance(hsc, (int, float)) and hsc >= _SILENCE_TRIGGER_HOURS)
    salient = {
        "ticktick_overdue": situation.get("ticktick_overdue") or [],
        "due_followups": [f.get("id") for f in (situation.get("due_followups") or [])],
        "calendar_trigger": _calendar_has_gap_or_overload(
            situation.get("calendar") or [], situation.get("now_context") or {}
        ),
        "meals_since_last_tick": len(situation.get("meals_since_last_tick") or []),
        "habit_pending": [h.get("id") for h in (situation.get("habit_pending") or [])],
        "recovery_flags": sorted((situation.get("recovery") or {}).get("flags") or []),
        "silence_bucket": silence_bucket,
    }
    blob = json.dumps(salient, sort_keys=True, ensure_ascii=False, default=str)
    return _hashlib.sha256(blob.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Insert the gate in `run_autonomous_tick`**

After the follow-up block (~1718) and before the Layer-1 triage `try:` (~1719), add:

```python
    # Layer 0.5 — change-detection gate (MEM-05 efficiency). If the salient
    # trigger signals are byte-identical to the last tick's, there is nothing
    # new to judge: skip the (costly, TPM-limited) Groq call and stay silent.
    # Fail-open: any store error → proceed with the normal triage call.
    try:
        _sig_store = _tick_signature_store()
        _signature = _compute_signal_signature(situation)
        _last_signature = _sig_store.get()
        if _last_signature is not None and _signature == _last_signature:
            decision["trail"].append("signals_unchanged_since_last_tick")
            await _write_tick_log(now, situation, decision)
            return decision
        _sig_store.set(_signature)
    except Exception:
        logger.warning("autonomous: change-detection gate errored; proceeding", exc_info=True)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_autonomous.py -k "signature or silence_bucket or unchanged" -q`
Expected: PASS.

- [ ] **Step 6: Full affected-file sweep**

Run: `.venv/bin/python -m pytest tests/test_autonomous.py tests/test_token_budget.py tests/test_tick_brain.py tests/test_firestore_db.py tests/test_llm_client.py -q`
Expected: all PASS (no regressions).

- [ ] **Step 7: Commit**

```bash
git add core/autonomous.py tests/test_autonomous.py
git commit -m "feat(groq): change-detection skip gate on autonomous tick (fewer Groq calls, fail-open)"
```

---

### Task 7: Deploy config + invariant docs

**Files:**
- Modify: `.github/workflows/deploy.yml` (`TICK_BRAIN_MAX_TOKENS` in `--set-env-vars`)
- Modify: `CLAUDE.md` (tick-brain row / invariants — correct "6000/8000 TPM" and note the per-request guard target)
- Modify: `docs/DEPLOYMENT.md` (operator note on the tick-efficiency change + live-verify step)

- [ ] **Step 1: Point the deployed env at the new budget**

In `.github/workflows/deploy.yml`, find `TICK_BRAIN_MAX_TOKENS=2048` in the `--set-env-vars` block and change it to `TICK_BRAIN_MAX_TOKENS=1024` (or the Step-1/Task-2 measured value). If the value is not present in deploy.yml (currently set out-of-band on Cloud Run), ADD it to the `--set-env-vars` list so the code default and deployed value can't drift (the deploy clobbers out-of-band env).

- [ ] **Step 2: Correct the invariant docs**

In `CLAUDE.md`, update the tick-brain note: Groq free tier is **8,000 tokens/request (TPM)** and **200K tokens/day (TPD)**; every tick-brain request must satisfy `input + max_tokens ≤ 7,200` (guarded by `tests/test_token_budget.py`); `reasoning_effort=low` + `max_tokens=1024` keep it admissible. Add a one-line invariant: "Tick-brain requests are admission-controlled to Groq's 8K TPM/request ceiling — the token-budget guard target is 7,200, never raise it to mask a prompt-bloat regression."

- [ ] **Step 3: Operator note**

In `docs/DEPLOYMENT.md`, add a short section: what changed, the live-verify step (below), and the deferred adaptive-controller + same-minute-collision watch items from the spec.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/deploy.yml CLAUDE.md docs/DEPLOYMENT.md
git commit -m "chore(groq): deploy TICK_BRAIN_MAX_TOKENS=1024 + correct TPM invariant docs"
```

---

## Rollout & live verification (after all tasks merged + deployed)

1. Push → CI → Cloud Run; confirm a new `klaus-agent-00NNN` revision is serving 100%.
2. Within one tick cycle (~20 min), verify the fix in logs:
   ```bash
   gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="klaus-agent" AND textPayload:"api.groq.com"' --project klaus-agent --freshness=1h --limit=10 --format="value(textPayload)"
   ```
   Expected: `200 OK` on the autonomous ticks; the `413 ... TPM: Limit 8000` line gone.
3. Confirm the ledger increments (Groq primary succeeding) and `tick_autonomous_calls` rises in `llm_usage/<today>` while `tick_autonomous_fallback_calls` stops climbing.
4. Watch item (spec): if any residual `413` appears at a `:00` boundary, it's the heartbeat+autonomous same-minute TPM collision — stagger the heartbeat tick-brain pass off `:00` (follow-up, not this plan).

## Self-Review

- **Spec coverage:** 1a→Task 1; 1b→Task 2; 1c(max_tokens+truncation)→Task 2; 1d→Task 4; 1e→Task 3; 2a/2c→Task 6; 2b→Task 5; deploy/invariants→Task 7; rollout→Rollout section. Lever 3 explicitly deferred (spec + Task 7 docs). All covered.
- **Placeholders:** none — every code/test step carries real content. The two "implementer: match the real render helper names" notes point at existing functions the executor must read (`_render_training_reality_tight`/`_render_conversation_tail_tight`, `GroqTokenLedgerStore` test fixture) rather than leaving logic unspecified.
- **Type consistency:** `extra_params: dict | None` consistent across Tasks 1-2; `_compute_signal_signature -> str` and `TickSignatureStore.get()->str|None`/`.set(str)` consistent across Tasks 5-6; `_DEFAULT_MAX_TOKENS` (Task 2) consumed by the guard (Task 3) and deploy env (Task 7).
