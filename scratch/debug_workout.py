import os
import logging
from dotenv import load_dotenv

# Enable full verbose logging to stdout
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

# Load environment overrides
load_dotenv(override=True)

# Mock Conversation Store to avoid Firestore dependency during this test if wanted,
# or we can let it run as configured (which is memory-based in development).
os.environ["CONVERSATION_STORE"] = "memory"

from core.main import AgentOrchestrator

def main():
    print("Initialising AgentOrchestrator...")
    orchestrator = AgentOrchestrator()
    
    user_msg = "אתה יכול להוסיף לי אימון פלג גוף עליון מחר ב12:00?"
    user_id = 99999999
    
    print(f"\nSending message: '{user_msg}'")
    try:
        response = orchestrator.handle_message(user_msg, user_id=user_id)
        print("\n=== FINAL RESPONSE ===")
        print(response)
    except Exception as e:
        print(f"\nError handling message: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
