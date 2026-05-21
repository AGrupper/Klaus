import os
from dotenv import load_dotenv
from core.auth_google import build_auth_manager_from_env

load_dotenv(override=True)

manager = build_auth_manager_from_env()
# Force interactive consent bypass loading the cache
creds = manager._run_consent_flow()
manager._persist_token(creds)
print("SUCCESSFULLY RE-AUTHENTICATED AND SAVED TO SECRET MANAGER")
