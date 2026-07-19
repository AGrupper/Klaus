"""Unit tests for llm_client backends (Gemini and OpenAI) image block support."""
import pytest
from unittest.mock import MagicMock, patch
from core.llm_client import _GeminiBackend, _OpenAIBackend


def test_gemini_backend_convert_messages():
    # Construct with dummy model and key
    backend = _GeminiBackend("gemini-3.5-flash", "fake-api-key")

    # 1. Test standard text messages conversion
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"}
    ]
    gemini_contents = backend._convert_messages(messages)
    assert len(gemini_contents) == 2
    assert gemini_contents[0].role == "user"
    assert gemini_contents[0].parts[0].text == "hello"
    assert gemini_contents[1].role == "model"
    assert gemini_contents[1].parts[0].text == "hi"

    # 2. Test multimodal (text + image) messages conversion
    messages_with_image = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "What is this image?"},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": "ZmFrZS1pbWFnZS1kYXRh"  # "fake-image-data"
                    }
                }
            ]
        }
    ]

    gemini_contents = backend._convert_messages(messages_with_image)

    assert len(gemini_contents) == 1
    assert gemini_contents[0].role == "user"
    assert len(gemini_contents[0].parts) == 2
    assert gemini_contents[0].parts[0].text == "What is this image?"
    
    inline_data = gemini_contents[0].parts[1].inline_data
    assert inline_data is not None
    assert inline_data.mime_type == "image/jpeg"
    assert inline_data.data == b"fake-image-data"


def test_openai_backend_convert_messages():
    backend = _OpenAIBackend("gpt-4o", "fake-api-key")

    # 1. Test text-only conversion
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"}
    ]
    openai_msgs = backend._convert_messages(messages, system="You are Klaus")
    assert len(openai_msgs) == 3
    assert openai_msgs[0] == {"role": "system", "content": "You are Klaus"}
    assert openai_msgs[1] == {"role": "user", "content": "hello"}
    assert openai_msgs[2] == {"role": "assistant", "content": "hi"}

    # 2. Test multimodal (text + image) conversion
    messages_with_image = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "What is this?"},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": "ZmFrZS1pbWFnZS1kYXRh"
                    }
                }
            ]
        }
    ]
    openai_msgs = backend._convert_messages(messages_with_image, system=None)
    assert len(openai_msgs) == 1
    assert openai_msgs[0]["role"] == "user"
    assert len(openai_msgs[0]["content"]) == 2
    assert openai_msgs[0]["content"][0] == {"type": "text", "text": "What is this?"}
    assert openai_msgs[0]["content"][1] == {
        "type": "image_url",
        "image_url": {
            "url": "data:image/jpeg;base64,ZmFrZS1pbWFnZS1kYXRh"
        }
    }


def test_openai_backend_convert_messages_with_reasoning_content():
    backend = _OpenAIBackend("gpt-4o", "fake-api-key")

    # 1. Test simple text message with reasoning_content
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi", "reasoning_content": "thinking..."}
    ]
    openai_msgs = backend._convert_messages(messages, system=None)
    assert len(openai_msgs) == 2
    assert openai_msgs[0] == {"role": "user", "content": "hello"}
    assert openai_msgs[1] == {"role": "assistant", "content": "hi", "reasoning_content": "thinking..."}

    # 2. Test assistant message with tool calls and reasoning_content
    messages_with_tools = [
        {"role": "user", "content": "run tool"},
        {
            "role": "assistant",
            "reasoning_content": "let's run a tool",
            "content": [
                {"type": "text", "text": "I will run the tool now."},
                {
                    "type": "tool_use",
                    "id": "call_123",
                    "name": "recall",
                    "input": {"query": "test"}
                }
            ]
        }
    ]
    openai_msgs = backend._convert_messages(messages_with_tools, system=None)
    assert len(openai_msgs) == 2
    assert openai_msgs[0] == {"role": "user", "content": "run tool"}
    assert openai_msgs[1] == {
        "role": "assistant",
        "content": "I will run the tool now.",
        "reasoning_content": "let's run a tool",
        "tool_calls": [{
            "id": "call_123",
            "type": "function",
            "function": {
                "name": "recall",
                "arguments": '{"query": "test"}'
            }
        }]
    }


def test_calendar_manager_get_ready_no_workout():
    from mcp_tools.calendar_tool import GoogleCalendarManager
    mock_auth = MagicMock()
    mock_service = MagicMock()
    mock_auth.calendar_service.return_value = mock_service

    # Mock service.events().insert().execute()
    mock_execute = MagicMock(return_value={"id": "dummy-event-id"})
    mock_insert = MagicMock()
    mock_insert.execute = mock_execute
    mock_service.events().insert.return_value = mock_insert
    # Workouts resolve the Training calendar via get_calendar_id_by_name, which
    # paginates calendarList until nextPageToken is falsy. A bare MagicMock returns
    # a truthy nextPageToken forever (infinite loop + unbounded call recording).
    # Give it a terminating page, exactly as a real API would.
    mock_service.calendarList.return_value.list.return_value.execute.return_value = {"items": []}

    manager = GoogleCalendarManager(mock_auth)

    # The Get Ready guard: even with is_workout=True, a 'Get Ready:' event must
    # never itself be treated as a workout (no nested prep block).
    result = manager.create_event(
        summary="Get Ready: Long Run with Brother",
        start_iso="2026-05-22T08:00:00+03:00",
        end_iso="2026-05-22T09:00:00+03:00",
        is_workout=True,
    )

    assert "error" not in result
    assert result["event_id"] == "dummy-event-id"
    # It should NOT have created a get_ready_event_id because the guard forced False!
    assert "get_ready_event_id" not in result

    # Verify that insert was only called ONCE (for the main event, not the prep event)
    assert mock_service.events().insert.call_count == 1

    # An explicit workout (is_workout=True) creates the prep block — training blocks
    # are caller-judged now, not keyword-detected.
    mock_service.events().insert.reset_mock()
    result_workout = manager.create_event(
        summary="Long Run with Brother",
        start_iso="2026-05-22T08:00:00+03:00",
        end_iso="2026-05-22T09:00:00+03:00",
        is_workout=True,
    )

    assert "error" not in result_workout
    assert result_workout["event_id"] == "dummy-event-id"
    # It SHOULD have created a get_ready_event_id because is_workout was True!
    assert result_workout["get_ready_event_id"] == "dummy-event-id"

    # Verify that insert was called TWICE (for main event and the prep event)
    assert mock_service.events().insert.call_count == 2


def test_calendar_manager_is_workout_explicit_overrides():
    from mcp_tools.calendar_tool import GoogleCalendarManager
    mock_auth = MagicMock()
    mock_service = MagicMock()
    mock_auth.calendar_service.return_value = mock_service

    # Mock service.events().insert().execute()
    mock_execute = MagicMock(return_value={"id": "dummy-event-id"})
    mock_insert = MagicMock()
    mock_insert.execute = mock_execute
    mock_service.events().insert.return_value = mock_insert
    # Workouts resolve the Training calendar via get_calendar_id_by_name, which
    # paginates calendarList until nextPageToken is falsy. A bare MagicMock returns
    # a truthy nextPageToken forever (infinite loop + unbounded call recording).
    # Give it a terminating page, exactly as a real API would.
    mock_service.calendarList.return_value.list.return_value.execute.return_value = {"items": []}

    manager = GoogleCalendarManager(mock_auth)

    # 1. Test is_workout=True explicitly on a non-workout keyword summary (e.g. "Tennis Session")
    result_true = manager.create_event(
        summary="Tennis Session",
        start_iso="2026-05-22T08:00:00+03:00",
        end_iso="2026-05-22T09:00:00+03:00",
        is_workout=True
    )
    assert "error" not in result_true
    assert result_true["event_id"] == "dummy-event-id"
    assert result_true["get_ready_event_id"] == "dummy-event-id"
    assert mock_service.events().insert.call_count == 2

    # 2. Test is_workout=False explicitly on a workout keyword summary (e.g. "Long Run with Brother")
    mock_service.events().insert.reset_mock()
    result_false = manager.create_event(
        summary="Long Run with Brother",
        start_iso="2026-05-22T08:00:00+03:00",
        end_iso="2026-05-22T09:00:00+03:00",
        is_workout=False
    )
    assert "error" not in result_false
    assert result_false["event_id"] == "dummy-event-id"
    assert "get_ready_event_id" not in result_false
    assert mock_service.events().insert.call_count == 1


def test_gemini_backend_thought_signature():
    # Construct with dummy model and key
    backend = _GeminiBackend("gemini-3.5-flash", "fake-api-key")

    # 1. Test text message with thought_signature
    messages_with_signature = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": "Hello, I am about to run a tool.",
                    "thought_signature": "ZW5jcnlwdGVkX3NpZ25hdHVyZQ=="  # base64 for "encrypted_signature"
                }
            ]
        }
    ]

    gemini_contents = backend._convert_messages(messages_with_signature)
    assert len(gemini_contents) == 1
    assert gemini_contents[0].role == "model"
    assert len(gemini_contents[0].parts) == 1
    assert gemini_contents[0].parts[0].text == "Hello, I am about to run a tool."
    assert gemini_contents[0].parts[0].thought_signature == b"encrypted_signature"

    # 2. Test tool_use message with thought_signature
    messages_with_tool_sig = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "list_calendar_events",
                    "name": "list_calendar_events",
                    "input": {},
                    "thought_signature": "ZW5jcnlwdGVkX3NpZ25hdHVyZQ=="
                }
            ]
        }
    ]

    gemini_contents_tool = backend._convert_messages(messages_with_tool_sig)
    assert len(gemini_contents_tool) == 1
    assert gemini_contents_tool[0].role == "model"
    assert len(gemini_contents_tool[0].parts) == 1
    assert gemini_contents_tool[0].parts[0].function_call is not None
    assert gemini_contents_tool[0].parts[0].function_call.name == "list_calendar_events"
    assert gemini_contents_tool[0].parts[0].thought_signature == b"encrypted_signature"


def test_gemini_backend_convert_tools():
    backend = _GeminiBackend("gemini-3.5-flash", "fake-api-key")
    tools = [
        {
            "name": "delegate_to_worker",
            "description": "Delegate a task to the worker agent",
            "input_schema": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "The task to delegate"}
                },
                "required": ["task"]
            }
        },
        {
            "name": "recall",
            "description": "Recall long-term memories",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Query string"}
                },
                "required": ["query"]
            }
        }
    ]
    converted = backend._convert_tools(tools)
    assert len(converted) == 1
    declarations = converted[0].function_declarations
    names = [d.name for d in declarations]
    assert "delegate_to_worker" in names
    assert "recall" in names



# --------------------------------------------------------------------------- #
# Client timeouts — a hung provider must never stall an agent turn for the    #
# SDK-default 10 minutes (observed: 6.5-minute DeepSeek hang on 2026-06-12).  #
# --------------------------------------------------------------------------- #


def test_openai_backend_sets_timeout_and_capped_retries():
    backend = _OpenAIBackend("deepseek-v4-flash", "fake-api-key")
    assert backend.client.timeout == 120.0
    assert backend.client.max_retries == 1


def test_anthropic_backend_sets_timeout_and_capped_retries():
    from core.llm_client import _AnthropicBackend
    backend = _AnthropicBackend("claude-haiku-4-5", "fake-api-key")
    assert backend.client.timeout == 120.0
    assert backend.client.max_retries == 1


def test_gemini_backend_sets_timeout():
    with patch("google.genai.Client") as mock_client_cls:
        _GeminiBackend("gemini-3.5-flash", "fake-api-key")
    _, kwargs = mock_client_cls.call_args
    http_options = kwargs["http_options"]
    # google-genai HttpOptions.timeout is in milliseconds
    timeout_ms = getattr(http_options, "timeout", None) or http_options["timeout"]
    assert timeout_ms == 120_000


def test_llm_timeout_env_override(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "45")
    backend = _OpenAIBackend("deepseek-v4-flash", "fake-api-key")
    assert backend.client.timeout == 45.0


# --------------------------------------------------------------------------- #
# Anthropic prompt caching + cache-token metering + param audit (BRAIN-02/05) #
# --------------------------------------------------------------------------- #


def _make_anthropic_response(text="hi", cache_read=0, cache_write=0,
                              in_tokens=100, out_tokens=20):
    """Build a MagicMock standing in for an anthropic.types.Message response."""
    block = MagicMock()
    block.type = "text"
    block.text = text

    usage = MagicMock()
    usage.input_tokens = in_tokens
    usage.output_tokens = out_tokens
    usage.cache_read_input_tokens = cache_read
    usage.cache_creation_input_tokens = cache_write

    response = MagicMock()
    response.content = [block]
    response.stop_reason = "end_turn"
    response.usage = usage
    return response


def test_anthropic_backend_sends_cache_control_system_block():
    from core.llm_client import _AnthropicBackend
    backend = _AnthropicBackend("claude-sonnet-5", "fake-api-key")
    backend.client.messages.stream = MagicMock(
        return_value=_make_anthropic_stream([], _make_anthropic_response())
    )

    backend.chat(
        [{"role": "user", "content": "hello"}],
        system="You are Klaus.",
    )

    _, kwargs = backend.client.messages.stream.call_args
    system_kwarg = kwargs["system"]
    assert isinstance(system_kwarg, list)
    assert len(system_kwarg) == 1
    assert system_kwarg[0]["type"] == "text"
    assert system_kwarg[0]["text"] == "You are Klaus."
    assert system_kwarg[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_anthropic_backend_no_system_block_when_system_empty():
    from core.llm_client import _AnthropicBackend
    backend = _AnthropicBackend("claude-sonnet-5", "fake-api-key")
    backend.client.messages.stream = MagicMock(
        return_value=_make_anthropic_stream([], _make_anthropic_response())
    )

    backend.chat([{"role": "user", "content": "hello"}], system=None)

    _, kwargs = backend.client.messages.stream.call_args
    assert "system" not in kwargs


def test_anthropic_backend_extracts_cache_tokens():
    from core.llm_client import _AnthropicBackend
    backend = _AnthropicBackend("claude-sonnet-5", "fake-api-key")
    backend.client.messages.stream = MagicMock(
        return_value=_make_anthropic_stream(
            [], _make_anthropic_response(cache_read=500, cache_write=1200)
        )
    )

    result = backend.chat(
        [{"role": "user", "content": "hello"}], system="You are Klaus."
    )

    assert result["usage"]["cache_read_tokens"] == 500
    assert result["usage"]["cache_write_tokens"] == 1200


def test_anthropic_backend_cache_tokens_default_zero_when_absent():
    from core.llm_client import _AnthropicBackend
    backend = _AnthropicBackend("claude-sonnet-5", "fake-api-key")
    # Simulate an older SDK/response shape with no cache fields at all.
    response = _make_anthropic_response()
    del response.usage.cache_read_input_tokens
    del response.usage.cache_creation_input_tokens
    backend.client.messages.stream = MagicMock(
        return_value=_make_anthropic_stream([], response)
    )

    result = backend.chat([{"role": "user", "content": "hello"}], system="sys")

    assert result["usage"]["cache_read_tokens"] == 0
    assert result["usage"]["cache_write_tokens"] == 0


def test_anthropic_backend_no_forbidden_params_on_smart_path():
    from core.llm_client import _AnthropicBackend
    backend = _AnthropicBackend("claude-sonnet-5", "fake-api-key")
    backend.client.messages.stream = MagicMock(
        return_value=_make_anthropic_stream([], _make_anthropic_response())
    )

    # Smart-path call: no temperature, no explicit thinking config, no tools.
    backend.chat([{"role": "user", "content": "hello"}], system="You are Klaus.")

    _, kwargs = backend.client.messages.stream.call_args
    assert "temperature" not in kwargs
    assert "top_p" not in kwargs
    assert "top_k" not in kwargs
    assert "thinking" not in kwargs


def test_anthropic_backend_temperature_still_gated_when_explicitly_passed():
    from core.llm_client import _AnthropicBackend
    backend = _AnthropicBackend("claude-haiku-4-5", "fake-api-key")
    backend.client.messages.stream = MagicMock(
        return_value=_make_anthropic_stream([], _make_anthropic_response())
    )

    backend.chat(
        [{"role": "user", "content": "hello"}], system=None, temperature=0.6
    )

    _, kwargs = backend.client.messages.stream.call_args
    assert kwargs["temperature"] == 0.6


def test_max_tokens_raised_for_thinking_headroom():
    from core.llm_client import MAX_TOKENS
    assert MAX_TOKENS >= 16000


def test_llm_client_chat_meters_cache_tokens(monkeypatch):
    """LLMClient.chat must thread cache tokens into compute_cost + LLMUsageStore.record."""
    from core.llm_client import LLMClient

    client = LLMClient(backend="anthropic", model="claude-sonnet-5", api_key="fake-key")
    client._impl.client.messages.stream = MagicMock(
        return_value=_make_anthropic_stream(
            [], _make_anthropic_response(cache_read=300, cache_write=800,
                                         in_tokens=1000, out_tokens=50)
        )
    )

    monkeypatch.setenv("GCP_PROJECT_ID", "fake-project")

    captured = {}

    class _FakeLLMUsageStore:
        def __init__(self, project_id, database):
            captured["project_id"] = project_id

        def record(self, **kwargs):
            captured["record_kwargs"] = kwargs

    with patch("memory.firestore_db.LLMUsageStore", _FakeLLMUsageStore), \
         patch("core.pricing.compute_cost", return_value=0.0042) as mock_compute_cost:
        client.chat(
            [{"role": "user", "content": "hello"}],
            system="You are Klaus.",
            purpose="smart",
        )

    _, compute_kwargs = mock_compute_cost.call_args
    assert compute_kwargs.get("cache_read_tokens") == 300
    assert compute_kwargs.get("cache_write_tokens") == 800

    assert captured["record_kwargs"]["cache_read_tokens"] == 300
    assert captured["record_kwargs"]["cache_write_tokens"] == 800


def test_gemini_backend_converts_document_block_to_pdf_part():
    """Anthropic 'document' blocks (hub PDF attachments) must convert to a
    Part.from_bytes with the PDF mime — Gemini reads PDF bytes natively, so the
    brain-fallback tier keeps PDF vision when Sonnet is down."""
    backend = _GeminiBackend("gemini-3.5-flash", "fake-api-key")

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Summarize this"},
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": "ZmFrZS1wZGYtZGF0YQ==",  # "fake-pdf-data"
                    },
                },
            ],
        }
    ]
    contents = backend._convert_messages(messages)
    assert len(contents) == 1
    parts = contents[0].parts
    assert parts[0].text == "Summarize this"
    inline = parts[1].inline_data
    assert inline.mime_type == "application/pdf"
    assert inline.data == b"fake-pdf-data"


# --------------------------------------------------------------------------- #
# Streaming (hub streaming feature): on_text_delta callback                   #
# --------------------------------------------------------------------------- #


def _make_anthropic_stream(chunks, final_response):
    """Context-manager mock standing in for client.messages.stream(...)."""
    stream = MagicMock()
    stream.text_stream = iter(chunks)
    stream.get_final_message.return_value = final_response
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=stream)
    cm.__exit__ = MagicMock(return_value=False)
    return cm


def test_anthropic_backend_streams_deltas_when_callback_given():
    """With on_text_delta, the Anthropic backend uses messages.stream, forwards
    each text chunk, and still returns the standard unified envelope."""
    from core.llm_client import _AnthropicBackend
    backend = _AnthropicBackend("claude-sonnet-5", "fake-api-key")
    final = _make_anthropic_response(text="Hello there", in_tokens=42, out_tokens=7)
    backend.client.messages.stream = MagicMock(
        return_value=_make_anthropic_stream(["Hello ", "there"], final)
    )
    backend.client.messages.create = MagicMock()

    deltas: list[str] = []
    result = backend.chat(
        [{"role": "user", "content": "hi"}],
        on_text_delta=deltas.append,
    )

    assert deltas == ["Hello ", "there"]
    assert result["text"] == "Hello there"
    assert result["usage"]["in_tokens"] == 42
    assert result["usage"]["out_tokens"] == 7
    backend.client.messages.create.assert_not_called()


def test_anthropic_backend_without_callback_also_streams():
    """Without on_text_delta the Anthropic backend must STILL use messages.stream:
    non-streaming waits in one silent read while the model generates, so httpx's
    read timeout fires at LLM_TIMEOUT_SECONDS wall-clock on any long generation
    (2026-07-19: weekly-review compose timed out at 120s, billed 2x, unmetered).
    SSE chunks reset the read timeout, so slow-but-alive generations survive."""
    from core.llm_client import _AnthropicBackend
    backend = _AnthropicBackend("claude-sonnet-5", "fake-api-key")
    final = _make_anthropic_response(text="Long compose", in_tokens=9, out_tokens=3)
    backend.client.messages.stream = MagicMock(
        return_value=_make_anthropic_stream([], final)
    )
    backend.client.messages.create = MagicMock()

    result = backend.chat([{"role": "user", "content": "hi"}])

    assert result["text"] == "Long compose"
    assert result["usage"]["in_tokens"] == 9
    backend.client.messages.stream.assert_called_once()
    backend.client.messages.create.assert_not_called()


def test_anthropic_backend_callback_exception_propagates():
    """A raising callback (TurnCancelled from the hub stop button) must unwind
    the stream and propagate — never be swallowed into an LLMError."""
    from core.llm_client import _AnthropicBackend

    class _Cancel(Exception):
        pass

    backend = _AnthropicBackend("claude-sonnet-5", "fake-api-key")
    backend.client.messages.stream = MagicMock(
        return_value=_make_anthropic_stream(["a", "b"], _make_anthropic_response())
    )

    def _boom(_chunk):
        raise _Cancel()

    with pytest.raises(_Cancel):
        backend.chat([{"role": "user", "content": "hi"}], on_text_delta=_boom)


def test_llm_client_facade_forwards_on_text_delta():
    """LLMClient.chat must pass on_text_delta through to the backend."""
    from core.llm_client import LLMClient
    client = LLMClient(backend="anthropic", model="claude-sonnet-5", api_key="fake")
    client._impl = MagicMock()
    client._impl.chat.return_value = {
        "text": "ok", "tool_calls": [], "stop_reason": "end_turn",
        "usage": {"in_tokens": 1, "out_tokens": 1},
    }
    cb = lambda _s: None  # noqa: E731

    client.chat([{"role": "user", "content": "hi"}], on_text_delta=cb)

    _, kwargs = client._impl.chat.call_args
    assert kwargs.get("on_text_delta") is cb


def test_gemini_and_openai_backends_accept_and_ignore_callback():
    """Fallback tiers don't stream — but must not crash when the kwarg is passed."""
    backend = _OpenAIBackend("deepseek-v4-flash", "fake-api-key")
    fake_completion = MagicMock()
    fake_completion.choices = [MagicMock()]
    fake_completion.choices[0].message.content = "ok"
    fake_completion.choices[0].message.tool_calls = None
    fake_completion.choices[0].finish_reason = "stop"
    fake_completion.usage.prompt_tokens = 1
    fake_completion.usage.completion_tokens = 1
    backend.client.chat.completions.create = MagicMock(return_value=fake_completion)

    result = backend.chat(
        [{"role": "user", "content": "hi"}],
        on_text_delta=lambda _s: None,
    )
    assert result["text"] == "ok"


def test_anthropic_backend_mid_stream_transport_error_becomes_llmerror():
    """A transport error raised WHILE consuming the SSE stream (httpx.ReadTimeout
    etc.) must map to LLMError like any other Anthropic failure — the SDK does
    not wrap mid-stream transport errors (anthropic/_streaming.py yields raw
    from response.iter_bytes()), and a raw httpx exception bypasses the whole
    Sonnet->Gemini->Haiku fallback chain in _run_smart_loop (CR-01)."""
    import httpx
    from core.llm_client import _AnthropicBackend, LLMError
    backend = _AnthropicBackend("claude-sonnet-5", "fake-api-key")
    stream = MagicMock()
    stream.get_final_message.side_effect = httpx.ReadTimeout("mid-stream read timeout")
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=stream)
    cm.__exit__ = MagicMock(return_value=False)
    backend.client.messages.stream = MagicMock(return_value=cm)

    with pytest.raises(LLMError):
        backend.chat([{"role": "user", "content": "hi"}])


def test_anthropic_backend_callback_exception_still_propagates_untouched():
    """The hub TurnCancelled path: a NON-httpx exception raised by the delta
    callback must still propagate as-is, never become LLMError (which would
    re-run a cancelled turn through the fallback tiers)."""
    class TurnCancelled(Exception):
        pass

    from core.llm_client import _AnthropicBackend, LLMError
    backend = _AnthropicBackend("claude-sonnet-5", "fake-api-key")
    stream = MagicMock()
    stream.text_stream = iter(["chunk1", "chunk2"])
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=stream)
    cm.__exit__ = MagicMock(return_value=False)
    backend.client.messages.stream = MagicMock(return_value=cm)

    def _cancel(_chunk):
        raise TurnCancelled()

    with pytest.raises(TurnCancelled):
        backend.chat([{"role": "user", "content": "hi"}], on_text_delta=_cancel)
