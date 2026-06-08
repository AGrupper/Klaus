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

