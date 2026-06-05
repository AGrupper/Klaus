import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# Add project root to sys.path
project_root = "/Users/amitgrupper/Desktop/Klaus"
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(project_root, ".env"), override=True)

from memory.firestore_db import _make_firestore_client

_TZ = ZoneInfo("Asia/Jerusalem")

def main():
    project_id = os.environ.get("GCP_PROJECT_ID")
    database = os.getenv("FIRESTORE_DATABASE", "(default)")
    print(f"Connecting to Firestore. Project: {project_id}, Database: {database}")
    
    client = _make_firestore_client(project_id, database)
    
    print("\n--- HEARTBEAT RUNS ---")
    runs_ref = client.collection("heartbeat_runs")
    for doc in runs_ref.stream():
        data = doc.to_dict()
        print(f"Job: {doc.id}")
        for k, v in sorted(data.items()):
            if isinstance(v, datetime):
                # Format to local time
                v_local = v.astimezone(_TZ)
                print(f"  {k}: {v} (Local: {v_local})")
            else:
                print(f"  {k}: {v}")
        print()

    print("\n--- MORNING BRIEFINGS STATE (Last 7 Days) ---")
    mb_ref = client.collection("morning_briefings")
    docs = list(mb_ref.stream())
    docs.sort(key=lambda d: d.id, reverse=True)
    for doc in docs[:7]:
        data = doc.to_dict()
        print(f"Date: {doc.id}")
        for k, v in sorted(data.items()):
            if isinstance(v, datetime):
                v_local = v.astimezone(_TZ)
                print(f"  {k}: {v} (Local: {v_local})")
            elif k == "sent_at" or k == "sync_detected_at":
                try:
                    dt = datetime.fromisoformat(v)
                    print(f"  {k}: {v} (Local: {dt.astimezone(_TZ)})")
                except Exception:
                    print(f"  {k}: {v}")
            else:
                print(f"  {k}: {v}")
        print()

if __name__ == "__main__":
    main()
