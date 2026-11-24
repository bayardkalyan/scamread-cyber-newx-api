"""Command line: python -m newsfeed run --out site"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path

from . import config
from .pipeline import run


def check_key() -> int:
    """Ask the API for one model name: free, and fails fast if the key is wrong."""
    import anthropic

    from .pipeline import clean_api_key, describe_api_key

    raw = os.environ.get("ANTHROPIC_API_KEY", "")
    print("Key:", describe_api_key(raw))
    if not clean_api_key(raw):
        print("No ANTHROPIC_API_KEY secret is set.")
        return 1
    try:
        anthropic.Anthropic(api_key=clean_api_key(raw)).models.list(limit=1)
    except anthropic.AuthenticationError:
        print("REJECTED: the key is not valid. Create a new one at platform.claude.com/settings/keys "
              "and update the ANTHROPIC_API_KEY secret.")
        return 1
    print("OK: the Claude API accepted the key.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="newsfeed", description="ScamRead cyber news feed")
    sub = parser.add_subparsers(dest="command", required=True)
    run_cmd = sub.add_parser("run", help="fetch, curate and write the JSON files once")
    run_cmd.add_argument("--out", type=Path, default=Path("site"), help="output folder (default: site)")
    run_cmd.add_argument("--sources", type=Path, default=config.SOURCES_FILE, help="sources.json to use")
    sub.add_parser("check-key", help="check that ANTHROPIC_API_KEY is accepted (free call)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.command == "check-key":
        raise SystemExit(check_key())
    if args.command == "run":
        status = run(args.out, sources_file=args.sources)
        summary = {k: status[k] for k in ("mode", "fetched_items", "new_items", "curated_items",
                                          "kept_items", "new_stories", "merged_sources")}
        summary["failed_sources"] = [s["name"] for s in status["sources"] if not s["ok"]]
        summary["errors"] = status["errors"]
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
