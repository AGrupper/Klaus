import os
import sys
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

# Add project root to sys.path
project_root = "/Users/amitgrupper/Desktop/Klaus"
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(project_root, ".env"), override=True)

# Set logging to see our token caching logs
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("test_garmin_persistence")

def get_secret(secret_name):
    try:
        res = subprocess.run(
            ["gcloud", "secrets", "versions", "access", "latest", f"--secret={secret_name}"],
            capture_output=True,
            text=True,
            check=True
        )
        return res.stdout.strip()
    except Exception as e:
        logger.error(f"Failed to fetch secret {secret_name}: {e}")
        sys.exit(1)

def main():
    logger.info("Retrieving Garmin credentials from Secret Manager...")
    email = get_secret("GARMIN_EMAIL")
    password = get_secret("GARMIN_PASSWORD")
    
    # Set the credentials in environment variables
    os.environ["GARMIN_EMAIL"] = email
    os.environ["GARMIN_PASSWORD"] = password
    
    from memory.firestore_db import _make_firestore_client
    project_id = os.environ["GCP_PROJECT_ID"]
    database = os.getenv("FIRESTORE_DATABASE", "(default)")
    client = _make_firestore_client(project_id, database)
    
    doc_ref = client.collection("config").document("garmin_tokens")
    
    logger.info("Clearing existing cached tokens in Firestore for clean test...")
    doc_ref.delete()
    
    from mcp_tools.garmin_tool import fetch_garmin_today
    
    logger.info("\n=== RUN 1: Full Email/Password Login ===")
    logger.info("This should trigger a full authentication flow and save tokens to Firestore.")
    data1 = fetch_garmin_today()
    logger.info(f"Run 1 completed. Data keys returned: {list(data1.keys()) if data1 else 'None'}")
    
    # Check if tokens were written to Firestore
    snap = doc_ref.get()
    if snap.exists and snap.to_dict().get("tokens_json"):
        logger.info("SUCCESS: Cached tokens successfully written to Firestore!")
    else:
        logger.error("FAILURE: Tokens were not found in Firestore config/garmin_tokens document.")
        sys.exit(1)
        
    logger.info("\n=== RUN 2: Token-based Login ===")
    logger.info("This should load tokens from Firestore and bypass full login.")
    data2 = fetch_garmin_today()
    logger.info(f"Run 2 completed. Data keys returned: {list(data2.keys()) if data2 else 'None'}")
    
    if data2:
        logger.info("\nSUCCESS: End-to-end Garmin token persistence works beautifully!")
    else:
        logger.error("FAILURE: Run 2 returned empty or failed.")
        sys.exit(1)

if __name__ == "__main__":
    main()
