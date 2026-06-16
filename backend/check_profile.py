"""
Standalone CLI to test the AJO profile-presence lookup without the UI.

Usage:
    python check_profile.py \
        --org-id "XXXX@AdobeOrg" \
        --sandbox prod \
        --client-id <id> \
        --client-secret <secret> \
        --entity jane@example.com \
        --namespace email

Secrets can also be supplied via env vars:
    AJO_ORG_ID, AJO_SANDBOX, AJO_CLIENT_ID, AJO_CLIENT_SECRET
"""

from __future__ import annotations

import argparse
import json
import sys

from app.config import settings
from app.services.ajo_profile_lookup import (
    AJOCredentials,
    AJOLookupError,
    AJOProfileClient,
)


def main() -> int:
    p = argparse.ArgumentParser(description="Check if a profile exists in AJO/AEP.")
    # Defaults come from the .env file (via app.config.settings).
    p.add_argument("--org-id", default=settings.ims_org_id)
    p.add_argument("--sandbox", default=settings.sandbox_name)
    p.add_argument("--client-id", default=settings.client_id)
    p.add_argument("--client-secret", default=settings.client_secret)
    p.add_argument("--entity", required=True, help="Identity value, e.g. an email.")
    p.add_argument("--namespace", default="email", help="Namespace code, e.g. email.")
    args = p.parse_args()

    missing = [
        n
        for n, v in [
            ("--org-id", args.org_id),
            ("--client-id", args.client_id),
            ("--client-secret", args.client_secret),
        ]
        if not v
    ]
    if missing:
        print(f"Missing required arguments: {', '.join(missing)}", file=sys.stderr)
        return 2

    creds = AJOCredentials(
        ims_org_id=args.org_id,
        sandbox_name=args.sandbox,
        client_id=args.client_id,
        client_secret=args.client_secret,
    )

    try:
        result = AJOProfileClient(creds).lookup_profile(args.entity, args.namespace)
    except AJOLookupError as exc:
        print(f"ERROR: {exc.message}", file=sys.stderr)
        if exc.detail:
            print(json.dumps(exc.detail, indent=2, default=str), file=sys.stderr)
        return 1

    status = "PRESENT" if result.present else "NOT PRESENT"
    print(f"[{status}] {result.entity_id} ({result.namespace}) — {result.message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
