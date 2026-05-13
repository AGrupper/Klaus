import asyncio
from core.main import AgentOrchestrator

async def main():
    orc = AgentOrchestrator()
    print("Sending message...")
    res = await asyncio.to_thread(orc.handle_message, "I'm working on Thursday from 11:00-17:00 and Saturday from 10:45-17:00 can you add it to my calendar?", 12345)
    print("Response:", res)

asyncio.run(main())
