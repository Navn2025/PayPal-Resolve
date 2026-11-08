"""Trusted local administrator commands. Never expose these through HTTP."""

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from .settings import Settings
from .storage import StoreError, configured_store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage local Resolve merchant access")
    parser.add_argument("--database", type=Path, help="Override the local database file")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-merchant", help="Create a merchant and one access key")
    create.add_argument("--name", required=True)
    issue = commands.add_parser("issue-key", help="Issue an additional merchant key")
    issue.add_argument("--merchant-id", type=UUID, required=True)
    issue.add_argument("--scope", choices=("full", "commerce"), default="full")
    revoke = commands.add_parser("revoke-key", help="Revoke a key by its public key ID")
    revoke.add_argument("--key-id", type=UUID, required=True)
    claim = commands.add_parser("claim-legacy", help="Explicitly assign unowned sample records")
    claim.add_argument("--merchant-id", type=UUID, required=True)
    args = parser.parse_args(argv)
    try:
        settings = Settings(database_url=None) if args.database is not None else Settings()
        store = configured_store(settings, sqlite_path=args.database)
        store.initialize()
        if args.command in ("create-merchant", "issue-key"):
            issued = (
                store.create_merchant(args.name) if args.command == "create-merchant"
                else store.issue_key(args.merchant_id, scope=args.scope)
            )
            print(json.dumps({
                "merchant": issued.merchant.model_dump(mode="json"),
                "key_id": str(issued.key_id), "api_key": issued.api_key,
            }, indent=2))
        elif args.command == "revoke-key":
            store.revoke_key(args.key_id)
            print(json.dumps({"key_id": str(args.key_id), "revoked": True}))
        else:
            print(json.dumps(store.claim_legacy(args.merchant_id)))
    except (StoreError, ValidationError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
