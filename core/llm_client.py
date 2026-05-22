"""Backend-agnostic LLM API wrapper.

Abstracts Anthropic, Google Gemini, and OpenAI behind a single interface so
the active backend can be swapped via environment variable without touching
call sites (per docs/TECHNICAL_PLAN.md §2).

All three backends convert:
  - Input:  Anthropic-format messages + tool schemas (canonical format)
  - Output: A unified response envelope dict

Canonical message format (mirrors Anthropic's API):
  {"role": "user"|"assistant", "content": str | list[block]}

  Content block types:
    {"type": "text",       "text": str}
    {"type": "tool_use",   "id": str, "name": str, "input": dict}
    {"type": "tool_result","tool_use_id": str, "content": str}

Unified response envelope:
  {
    "text":       str | None,         # final text response (None if only tool calls)
    "tool_calls": list[dict],         # [{"name": str, "id": str, "input": dict}, ...]
    "stop_reason": str,               # "end_turn" | "tool_use" | "max_tokens"
    "usage":      dict,               # {"in_tokens": int, "out_tokens": int}
  }
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

MAX_TOKENS = 4096


class LLMError(Exception):
    """Provider-agnostic LLM error, surfaced to the orchestrator."""

    def __init__(self, message: str, backend: str,
                 status_code: int | None = None) -> None:
        super().__init__(message)
        self.backend = backend
        self.status_code = status_code


class LLMClient:
    """Backend-agnostic facade. Delegates to a concrete backend class."""

    SUPPORTED_BACKENDS = ("anthropic", "gemini", "openai")

    def __init__(self, backend: str, model: str, api_key: str,
                 base_url: str | None = None) -> None:
        """Initialise the client for a specific backend + model.

        Args:
            backend:  One of "anthropic", "gemini", "openai".
            model:    Provider-specific model ID (e.g. "claude-opus-4-5-20251101").
            api_key:  API credential for the chosen backend.
            base_url: Optional URL override for OpenAI-compatible endpoints (e.g. Groq).
                      Ignored for anthropic/gemini backends.

        Raises:
            ValueError: If backend is not one of SUPPORTED_BACKENDS.
        """
        self.backend = backend
        self.model = model
        self.base_url = base_url

        if backend == "anthropic":
            self._impl: _BaseBackend = _AnthropicBackend(model, api_key)
        elif backend == "gemini":
            self._impl = _GeminiBackend(model, api_key)
        elif backend == "openai":
            self._impl = _OpenAIBackend(model, api_key, base_url=base_url)
        else:
            raise ValueError(
                f"Unsupported backend '{backend}'. "
                f"Choose from: {self.SUPPORTED_BACKENDS}"
            )

    def chat(self, messages: list[dict], *, system: str | None = None,
             tools: list[dict] | None = None,
             purpose: str = "") -> dict:
        """Send a multi-turn conversation and return a unified response.

        Args:
            messages: Conversation history in canonical Anthropic format.
            system:   System prompt string (injected by each backend as appropriate).
            tools:    Tool schemas in Anthropic tool_use format. Each backend
                      converts internally to its own wire format.
            purpose:  Caller label for usage metering (e.g. "smart", "worker", "tick").
                      Stored in LLMUsageStore — has no effect on the LLM call itself.

        Returns:
            Unified envelope: {"text", "tool_calls", "stop_reason", "usage"}
        """
        logger.debug(
            "chat backend=%s model=%s messages=%d tools=%d purpose=%s",
            self.backend, self.model, len(messages), len(tools or []), purpose,
        )
        result = self._impl.chat(messages, system=system, tools=tools)

        # --- Cost metering (never raises) ---
        try:
            usage = result.get("usage") or {}
            in_tok  = usage.get("in_tokens", 0) or 0
            out_tok = usage.get("out_tokens", 0) or 0
            from core.pricing import compute_cost
            cost = compute_cost(self.model, in_tok, out_tok)
            import os
            project_id = os.getenv("GCP_PROJECT_ID", "")
            if project_id:
                database = os.getenv("FIRESTORE_DATABASE", "(default)")
                from memory.firestore_db import LLMUsageStore
                LLMUsageStore(project_id, database).record(
                    model=self.model,
                    purpose=purpose,
                    in_tokens=in_tok,
                    out_tokens=out_tok,
                    cost=cost,
                )
        except Exception:
            logger.debug("LLM usage metering failed (non-fatal)", exc_info=True)

        return result


# ------------------------------------------------------------------ #
# Internal backend base                                              #
# ------------------------------------------------------------------ #

class _BaseBackend:
    """Marker base class for type-checking."""

    def chat(self, messages: list[dict], *, system: str | None,
             tools: list[dict] | None) -> dict:
        raise NotImplementedError


# ------------------------------------------------------------------ #
# Anthropic backend                                                  #
# ------------------------------------------------------------------ #

class _AnthropicBackend(_BaseBackend):
    """Anthropic Messages API. Uses Anthropic's format natively — no conversion."""

    def __init__(self, model: str, api_key: str) -> None:
        import anthropic  # lazy import: only loaded when this backend is used
        self.model = model
        self.client = anthropic.Anthropic(api_key=api_key)

    def chat(self, messages: list[dict], *, system: str | None = None,
             tools: list[dict] | None = None) -> dict:
        import anthropic

        # Strip thought_signature from messages to prevent Anthropic validation errors on fallback
        clean_messages = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if isinstance(content, str):
                clean_messages.append({"role": role, "content": content})
            else:
                clean_content = []
                for block in content:
                    clean_block = {k: v for k, v in block.items() if k != "thought_signature"}
                    clean_content.append(clean_block)
                clean_messages.append({"role": role, "content": clean_content})

        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "messages": clean_messages,
        }
        if system:
            kwargs["system"] = system
        if tools:
            # Anthropic tool format is our canonical format — pass through directly.
            kwargs["tools"] = tools

        try:
            response = self.client.messages.create(**kwargs)
        except anthropic.APIStatusError as exc:
            raise LLMError(
                str(exc), backend="anthropic", status_code=exc.status_code
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(
                f"Connection error to Anthropic API: {exc}", backend="anthropic"
            ) from exc

        text: str | None = None
        tool_calls: list[dict] = []

        for block in response.content:
            if block.type == "text":
                text = block.text
            elif block.type == "tool_use":
                tool_calls.append({
                    "name": block.name,
                    "id": block.id,
                    "input": block.input,
                })

        return {
            "text": text,
            "tool_calls": tool_calls,
            "stop_reason": response.stop_reason,
            "usage": {
                "in_tokens":  response.usage.input_tokens,
                "out_tokens": response.usage.output_tokens,
            },
        }


# ------------------------------------------------------------------ #
# Google Gemini backend (google-genai SDK >= 1.0)                   #
# ------------------------------------------------------------------ #

class _GeminiBackend(_BaseBackend):
    """Google Gemini via the google-genai SDK (current official SDK).

    Note: 'delegate_to_worker' is stripped from tool schemas before being
    sent to Gemini — it is a meta-tool intercepted by the orchestrator and
    not a real function Gemini should call.

    Gemini does not issue unique tool call IDs. We use the function name
    as the ID. This works correctly as long as the same function is not
    called twice in a single turn (which our prompts prevent).
    """

    def __init__(self, model: str, api_key: str) -> None:
        from google import genai  # lazy import
        self.model_name = model
        self.client = genai.Client(api_key=api_key)

    def chat(self, messages: list[dict], *, system: str | None = None,
             tools: list[dict] | None = None) -> dict:
        from google import genai
        from google.genai import types

        gemini_contents = self._convert_messages(messages)
        gemini_tools = self._convert_tools(tools) if tools else None

        config_kwargs: dict[str, Any] = {}
        config_kwargs["max_output_tokens"] = MAX_TOKENS
        if system:
            config_kwargs["system_instruction"] = system
        if gemini_tools:
            config_kwargs["tools"] = gemini_tools

        config = types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

        request_kwargs: dict[str, Any] = {
            "model": self.model_name,
            "contents": gemini_contents,
        }
        if config:
            request_kwargs["config"] = config

        try:
            response = self.client.models.generate_content(**request_kwargs)
        except Exception as exc:
            # google.api_core.exceptions.GoogleAPIError and subclasses
            raise LLMError(
                str(exc), backend="gemini",
                status_code=getattr(exc, "code", None),
            ) from exc

        import base64
        text: str | None = None
        tool_calls: list[dict] = []
        thought_sig: bytes | None = None

        if response.candidates:
            for part in response.candidates[0].content.parts:
                # Capture thought_signature if present and not a function call part
                is_fc = hasattr(part, "function_call") and part.function_call is not None and part.function_call.name
                if hasattr(part, "thought_signature") and part.thought_signature:
                    if not is_fc:
                        thought_sig = part.thought_signature

                # Check for text
                if hasattr(part, "text") and part.text:
                    text = part.text
                # Check for function call
                if is_fc:
                    fc = part.function_call
                    tool_calls.append({
                        "name": fc.name,
                        "id": fc.name,  # WHY: Gemini has no call IDs; name is unique per turn
                        "input": dict(fc.args),
                        "thought_signature": base64.b64encode(part.thought_signature).decode("utf-8") if getattr(part, "thought_signature", None) else None
                    })

        stop = "tool_use" if tool_calls else "end_turn"
        usage_meta = getattr(response, "usage_metadata", None)
        in_tokens  = getattr(usage_meta, "prompt_token_count", 0) or 0
        out_tokens = getattr(usage_meta, "candidates_token_count", 0) or 0
        return {
            "text": text,
            "tool_calls": tool_calls,
            "stop_reason": stop,
            "usage": {"in_tokens": in_tokens, "out_tokens": out_tokens},
            "thought_signature": base64.b64encode(thought_sig).decode("utf-8") if thought_sig else None
        }

    def _convert_messages(self, messages: list[dict]) -> list:
        """Convert Anthropic-format messages to google-genai Content objects."""
        from google.genai import types
        import base64

        contents = []
        for msg in messages:
            role = "model" if msg["role"] == "assistant" else "user"
            content = msg["content"]

            if isinstance(content, str):
                contents.append(
                    types.Content(role=role, parts=[types.Part(text=content)])
                )
                continue

            # Content is a list of typed blocks.
            parts = []
            for block in content:
                block_type = block.get("type")

                if block_type == "text":
                    thought_sig_b64 = block.get("thought_signature")
                    thought_sig_bytes = base64.b64decode(thought_sig_b64) if thought_sig_b64 else None
                    if thought_sig_bytes:
                        parts.append(
                            types.Part(
                                text=block["text"],
                                thought_signature=thought_sig_bytes,
                            )
                        )
                    else:
                        parts.append(types.Part(text=block["text"]))

                elif block_type == "image":
                    img_data = block["source"]["data"]
                    if isinstance(img_data, str):
                        img_bytes = base64.b64decode(img_data)
                    else:
                        img_bytes = img_data
                    parts.append(
                        types.Part.from_bytes(
                            data=img_bytes,
                            mime_type=block["source"]["media_type"],
                        )
                    )

                elif block_type == "tool_use":
                    # WHY: Gemini represents outgoing function calls as a Part with
                    # a FunctionCall sub-object, matched by name on the return trip.
                    thought_sig_b64 = block.get("thought_signature")
                    thought_sig_bytes = base64.b64decode(thought_sig_b64) if thought_sig_b64 else None
                    if thought_sig_bytes:
                        parts.append(
                            types.Part(
                                function_call=types.FunctionCall(
                                    name=block["name"],
                                    args=block["input"],
                                ),
                                thought_signature=thought_sig_bytes,
                            )
                        )
                    else:
                        parts.append(
                            types.Part.from_function_call(
                                name=block["name"],
                                args=block["input"],
                            )
                        )

                elif block_type == "tool_result":
                    # WHY: tool_use_id here is the function name (since we use the
                    # function name as the ID for Gemini — see class docstring).
                    parts.append(
                        types.Part.from_function_response(
                            name=block.get("tool_use_id", ""),
                            response={"content": block.get("content", "")},
                        )
                    )

            if parts:
                contents.append(types.Content(role=role, parts=parts))

        return contents

    def _convert_tools(self, tools: list[dict]) -> list:
        """Convert Anthropic-format tool schemas to Gemini FunctionDeclarations."""
        from google.genai import types

        declarations = []
        for tool in tools:
            declarations.append(
                types.FunctionDeclaration(
                    name=tool["name"],
                    description=tool.get("description", ""),
                    parameters=self._json_schema_to_gemini(
                        tool.get("input_schema", {"type": "object", "properties": {}})
                    ),
                )
            )

        return [types.Tool(function_declarations=declarations)] if declarations else []

    def _json_schema_to_gemini(self, schema: dict) -> Any:
        """Recursively convert a JSON Schema dict to a google.genai types.Schema.

        WHY: Gemini's Schema uses enum type constants instead of JSON Schema
        lowercase strings, and wraps properties recursively.
        """
        from google.genai import types

        TYPE_MAP = {
            "string":  types.Type.STRING,
            "number":  types.Type.NUMBER,
            "integer": types.Type.INTEGER,
            "boolean": types.Type.BOOLEAN,
            "array":   types.Type.ARRAY,
            "object":  types.Type.OBJECT,
        }

        schema_type = TYPE_MAP.get(schema.get("type", "string"), types.Type.STRING)

        properties: dict[str, Any] = {}
        if "properties" in schema:
            for key, val in schema["properties"].items():
                properties[key] = self._json_schema_to_gemini(val)

        items = None
        if "items" in schema:
            items = self._json_schema_to_gemini(schema["items"])

        return types.Schema(
            type=schema_type,
            description=schema.get("description") or None,
            properties=properties or None,
            required=schema.get("required") or None,
            items=items,
            enum=schema.get("enum") or None,
        )


# ------------------------------------------------------------------ #
# OpenAI-compatible backend                                          #
# ------------------------------------------------------------------ #

class _OpenAIBackend(_BaseBackend):
    """OpenAI chat completions API.

    Also works with OpenAI-compatible endpoints (e.g. Groq) by passing a
    custom base_url as a constructor param.
    """

    def __init__(self, model: str, api_key: str,
                 base_url: str | None = None) -> None:
        from openai import OpenAI  # lazy import
        self.model = model
        # WHY: base_url is now a constructor param so each caller (main brain vs tick-brain)
        # can target different endpoints without mutating global env vars.
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def chat(self, messages: list[dict], *, system: str | None = None,
             tools: list[dict] | None = None) -> dict:
        from openai import APIConnectionError, APIStatusError

        openai_messages = self._convert_messages(messages, system=system)
        openai_tools = self._convert_tools(tools) if tools else None

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": openai_messages,
            "max_tokens": MAX_TOKENS,
        }
        if openai_tools:
            kwargs["tools"] = openai_tools

        try:
            response = self.client.chat.completions.create(**kwargs)
        except APIStatusError as exc:
            raise LLMError(
                str(exc), backend="openai", status_code=exc.status_code
            ) from exc
        except APIConnectionError as exc:
            raise LLMError(
                f"Connection error to OpenAI API: {exc}", backend="openai"
            ) from exc

        choice = response.choices[0]
        msg = choice.message
        text = msg.content  # may be None if the model chose a tool call
        reasoning_content = getattr(msg, "reasoning_content", None)

        tool_calls: list[dict] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append({
                    "name": tc.function.name,
                    "id": tc.id,
                    "input": json.loads(tc.function.arguments),
                })

        stop_reason = "tool_use" if tool_calls else "end_turn"
        usage = response.usage
        return {
            "text": text,
            "tool_calls": tool_calls,
            "stop_reason": stop_reason,
            "usage": {
                "in_tokens":  getattr(usage, "prompt_tokens", 0) or 0,
                "out_tokens": getattr(usage, "completion_tokens", 0) or 0,
            },
            "reasoning_content": reasoning_content,
        }

    def _convert_messages(self, messages: list[dict], *,
                          system: str | None) -> list[dict]:
        """Convert canonical Anthropic-format messages to OpenAI message list."""
        openai_msgs: list[dict] = []

        if system:
            openai_msgs.append({"role": "system", "content": system})

        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            reasoning_content = msg.get("reasoning_content")

            if isinstance(content, str):
                openai_msg: dict[str, Any] = {"role": role, "content": content}
                if role == "assistant" and reasoning_content:
                    openai_msg["reasoning_content"] = reasoning_content
                openai_msgs.append(openai_msg)
                continue

            if role == "assistant":
                text_blocks = []
                image_blocks = []
                tool_calls = []
                for block in content:
                    block_type = block.get("type")
                    if block_type == "text":
                        text_blocks.append(block["text"])
                    elif block_type == "image":
                        img_data = block["source"]["data"]
                        media_type = block["source"]["media_type"]
                        image_blocks.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{media_type};base64,{img_data}"
                            }
                        })
                    elif block_type == "tool_use":
                        tool_calls.append({
                            "id": block["id"],
                            "type": "function",
                            "function": {
                                "name": block["name"],
                                "arguments": json.dumps(block["input"]),
                            },
                        })
                
                openai_content = None
                if image_blocks:
                    openai_content = [{"type": "text", "text": t} for t in text_blocks] + image_blocks
                elif text_blocks:
                    openai_content = "\n".join(text_blocks)
                
                openai_msg = {"role": "assistant", "content": openai_content}
                if tool_calls:
                    openai_msg["tool_calls"] = tool_calls
                if reasoning_content:
                    openai_msg["reasoning_content"] = reasoning_content
                openai_msgs.append(openai_msg)
                continue

            # Content is a list of typed blocks — may contain tool_use, tool_result, text, or image.
            # We accumulate consecutive text and image blocks in a single message's content list to support OpenAI's multimodal format.
            content_list = []
            has_media = False
            for block in content:
                block_type = block.get("type")

                if block_type == "text":
                    content_list.append({"type": "text", "text": block["text"]})

                elif block_type == "image":
                    has_media = True
                    img_data = block["source"]["data"]
                    media_type = block["source"]["media_type"]
                    content_list.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{img_data}"
                        }
                    })

                elif block_type == "tool_use":
                    if content_list:
                        openai_msg = {"role": role}
                        if has_media:
                            openai_msg["content"] = content_list
                        else:
                            openai_msg["content"] = content_list if len(content_list) > 1 else content_list[0]["text"]
                        
                        openai_msgs.append(openai_msg)
                        content_list = []
                        has_media = False

                    # WHY: OpenAI expects tool calls as a separate message field,
                    # not inside the content array.
                    tool_msg: dict[str, Any] = {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": block["id"],
                            "type": "function",
                            "function": {
                                "name": block["name"],
                                "arguments": json.dumps(block["input"]),
                            },
                        }],
                    }
                    openai_msgs.append(tool_msg)

                elif block_type == "tool_result":
                    if content_list:
                        openai_msg = {"role": role}
                        if has_media:
                            openai_msg["content"] = content_list
                        else:
                            openai_msg["content"] = content_list if len(content_list) > 1 else content_list[0]["text"]
                        
                        openai_msgs.append(openai_msg)
                        content_list = []
                        has_media = False

                    # WHY: OpenAI tool results use role="tool" (not "user") and
                    # reference tool_call_id to match the originating call.
                    openai_msgs.append({
                        "role": "tool",
                        "tool_call_id": block["tool_use_id"],
                        "content": str(block.get("content", "")),
                    })

            if content_list:
                openai_msg = {"role": role}
                if has_media:
                    openai_msg["content"] = content_list
                else:
                    openai_msg["content"] = content_list if len(content_list) > 1 else content_list[0]["text"]
                
                openai_msgs.append(openai_msg)

        return openai_msgs

    def _convert_tools(self, tools: list[dict]) -> list[dict]:
        """Convert Anthropic-format schemas to OpenAI function definitions."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get(
                        "input_schema",
                        {"type": "object", "properties": {}},
                    ),
                },
            }
            for t in tools
        ]
