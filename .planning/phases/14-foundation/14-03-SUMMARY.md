---
plan: 14-03
phase: 14-foundation
status: complete
---

# Plan 14-03: LLMClient Cost Metering + base_url Param

## What Was Built

`core/llm_client.py` surgically extended across 5 changes:

1. **`LLMClient.__init__` — `base_url` param added**: Propagates to `_OpenAIBackend`, enabling tick-brain (Plan 04) to target Groq without touching global env vars.
2. **`_OpenAIBackend.__init__` — `base_url` constructor param**: Replaces the hardcoded `os.getenv("OPENAI_BASE_URL")` env read. Zero `OPENAI_BASE_URL` references remain.
3. **`max_tokens` normalization**: `_GeminiBackend` gets `max_output_tokens=MAX_TOKENS` in `config_kwargs`; `_OpenAIBackend` gets `max_tokens=MAX_TOKENS` in kwargs.
4. **All 3 backends surface `"usage"` key**: `_AnthropicBackend` reads `response.usage.input_tokens/output_tokens`; `_GeminiBackend` reads `usage_metadata.prompt_token_count/candidates_token_count` via `getattr` with `0` fallback; `_OpenAIBackend` reads `usage.prompt_tokens/completion_tokens`.
5. **`LLMClient.chat()` — `purpose=""` param + metering**: After each backend call, computes cost via `compute_cost()` and records to `LLMUsageStore` (guarded by `GCP_PROJECT_ID` env var — silent no-op in local dev). Entire metering block wrapped in `try/except` — never raises.

## Key Files Modified

- `core/llm_client.py` — extended with usage metering, base_url param, max_tokens normalization

## Commits

- `a9c85a0` feat(14-03): thread token-usage metering through all LLM backends

## Verification

All 6 must-have checks passed:
- `base_url` in `LLMClient.__init__` ✓
- `purpose` in `LLMClient.chat` ✓
- `OPENAI_BASE_URL` references = 0 ✓
- `"usage"` key count = 6 (≥ 4) ✓
- `max_output_tokens` in GeminiBackend ✓
- Syntax valid (`ast.parse`) ✓

## Self-Check: PASSED
