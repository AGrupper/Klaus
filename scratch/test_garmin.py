import os
import sys
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

project_root = "/Users/amitgrupper/Desktop/Klaus"
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(project_root, ".env"), override=True)

from mcp_tools.garmin_tool import fetch_garmin_today
from garminconnect import Garmin

_TZ = ZoneInfo("Asia/Jerusalem")

def main():
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    print(f"Garmin Email: {email}")
    print(f"Garmin Password exists: {bool(password)}")
    
    # Try logging in directly
    print("\nAttempting Garmin Login...")
    try:
        api = Garmin(email=email, password=password)
        api.login()
        print("Garmin Login Successful!")
    except Exception as e:
        print(f"Garmin Login Failed: {e}")
        return

    # Try fetching data for today
    today = datetime.now(_TZ).date().isoformat()
    yesterday = (datetime.now(_TZ).date() - timedelta(days=1)).isoformat()
    
    for d in [today, yesterday]:
        print(f"\n--- Fetching Data for {d} ---")
        try:
            sleep_data = api.get_sleep_data(d)
            print(f"Sleep data keys: {list(sleep_data.keys()) if sleep_data else 'None'}")
            if sleep_data:
                dto = sleep_data.get("dailySleepDTO") or {}
                print(f"dailySleepDTO keys: {list(dto.keys()) if dto else 'None'}")
                score_obj = dto.get("sleepScores") or {}
                print(f"sleepScores: {score_obj}")
                sleep_secs = dto.get("sleepTimeSeconds") or 0
                sleep_hours = round(sleep_secs / 3600, 1) if sleep_secs else None
                print(f"sleepTimeSeconds: {sleep_secs} ({sleep_hours} hours)")
        except Exception as e:
            print(f"Error fetching sleep for {d}: {e}")

if __name__ == "__main__":
    main()
