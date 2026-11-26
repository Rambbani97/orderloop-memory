#!/usr/bin/env python3
"""Seed the 12 knowledge-base articles into a Meko datapack.

Uploads ``data/kb/*.md`` via the Meko MCP tool
``knowledgebase_upload_document`` (through the registered ``custom.meko``
connector CLI — the API key lives only in the Secure Vault and is never
read from env vars or files here). The REST API host is NOT registered in
the connector, so REST uploads are intentionally not used.

Requires: MEKO_DATAPACK_ID in env (or --datapack). Does nothing without it
— run ``python scripts/seed_kb.py --dry-run`` to list what would be uploaded.

Usage:
    python scripts/seed_kb.py --dry-run
    python scripts/seed_kb.py            # uploads to the datapack in env
    python scripts/seed_kb.py --datapack <id> --force   # re-upload all 12
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.factory import PROJECT_ROOT
from app.meko_client import MekoCLIClient, MekoConfig


def list_articles() -> list[Path]:
    return sorted((PROJECT_ROOT / "data" / "kb").glob("kb-*.md"))


def upload(client: MekoCLIClient, path: Path, poll: bool = True) -> dict:
    """Upload one article via MCP. Returns the tool result as a dict."""
    text = path.read_text(encoding="utf-8")
    result = client.knowledgebase_upload_document(path.name, text)
    if poll and result.get("ok") and result.get("document_key"):
        for _ in range(36):  # up to ~180s of polling (kb-02 once took >60s)
            status = client.knowledgebase_document_status(result["document_key"])
            state = str(status.get("status") or status.get("state") or status)
            if "complet" in state.lower() or "index" in state.lower():
                result["index_status"] = status
                break
            if "fail" in state.lower() or "error" in state.lower():
                result["index_status"] = status
                break
            time.sleep(5)
        else:
            result["index_status"] = {"status": "polling timed out"}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed KB articles into Meko")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--datapack", default=os.environ.get("MEKO_DATAPACK_ID", ""))
    parser.add_argument("--force", action="store_true",
                        help="re-upload even if already present (no-op check is skipped)")
    args = parser.parse_args()

    articles = list_articles()
    print(f"{len(articles)} KB articles in data/kb/")
    for path in articles:
        print(f"  {path.name} ({path.stat().st_size} bytes)")
    if args.dry_run:
        print("DRY RUN — nothing uploaded.")
        return 0

    if not args.datapack:
        print("ERROR: MEKO_DATAPACK_ID is not set (or pass --datapack <id>).",
              file=sys.stderr)
        return 2

    client = MekoCLIClient(MekoConfig(datapack_id=args.datapack))
    for path in articles:
        try:
            result = upload(client, path)
            print(f"  uploaded {path.name}: {json.dumps(result)[:300]}")
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"  FAILED {path.name}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
