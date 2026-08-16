"""Firestore store constructors shared by more than one route module.

Both the push routes and the settings route build a HubSettingsStore, and
duplicating the env plumbing in each is how the two drift onto different
databases. Not routes, so not a router — just the wiring they share.
"""
from __future__ import annotations

import os

def _get_push_store():
    """Return a PushSubscriptionStore instance using env-driven project/database config."""
    from memory.firestore_db import PushSubscriptionStore  # lazy import

    return PushSubscriptionStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )


def _get_hub_settings_store():
    """Return a HubSettingsStore instance using env-driven project/database config."""
    from memory.firestore_db import HubSettingsStore  # lazy import

    return HubSettingsStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
