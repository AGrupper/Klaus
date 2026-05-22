import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    api_key=os.environ["WORKER_AGENT_API_KEY"],
    base_url=os.environ["WORKER_AGENT_BASE_URL"],
)

try:
    print("Listing models in DeepSeek...")
    models = client.models.list()
    for m in models.data:
        print(f"- {m.id}")
except Exception as e:
    print(f"Error listing models: {e}")

try:
    print("\nCalling deepseek-v4-flash with a tool definition...")
    tools = [
        {
            "type": "function",
            "function": {
                "name": "check_calendar_free",
                "description": "Check if a specific time window is free.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "start_iso": {"type": "string"},
                        "end_iso": {"type": "string"},
                    },
                    "required": ["start_iso", "end_iso"],
                },
            },
        }
    ]
    response = client.chat.completions.create(
        model=os.environ["WORKER_AGENT_MODEL"],
        messages=[{"role": "user", "content": "Check if I'm free tomorrow from 12:00 to 13:00"}],
        tools=tools,
        tool_choice="auto",
    )
    print("Response choice 0 message:")
    msg = response.choices[0].message
    print(f"Text: {msg.content}")
    print(f"Tool calls: {msg.tool_calls}")
except Exception as e:
    print(f"Error testing tool call: {e}")

