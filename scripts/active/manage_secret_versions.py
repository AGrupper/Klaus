#!/usr/bin/env python3
"""Plan or apply bounded Secret Manager version retention for one secret.

The default mode is read-only. ``--apply`` disables old enabled versions and
destroys only versions that were already disabled before this invocation.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.secret_retention import apply_plan, plan_for_client


def main() -> int:
    """Print the plan and optionally apply it after explicit confirmation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="klaus-agent")
    parser.add_argument("--secret", default="klaus-google-oauth-token")
    parser.add_argument("--keep", type=int, default=2)
    parser.add_argument("--destroy-grace-days", type=int, default=7)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--confirm-secret",
        help="required with --apply; must exactly match --secret",
    )
    args = parser.parse_args()
    if args.apply and args.confirm_secret != args.secret:
        parser.error("--apply requires --confirm-secret to exactly match --secret")

    from google.cloud import secretmanager

    client = secretmanager.SecretManagerServiceClient()
    parent = f"projects/{args.project}/secrets/{args.secret}"
    plan = plan_for_client(
        client,
        parent,
        keep_count=args.keep,
        destroy_grace_days=args.destroy_grace_days,
    )
    print(json.dumps({"secret": args.secret, "plan": plan}, indent=2, sort_keys=True))
    if args.apply:
        apply_plan(client, parent, plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
