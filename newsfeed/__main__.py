"""Command line: python -m newsfeed run --out site"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from . import config
from .pipeline import run


def main() -> None:
    parser = argparse.ArgumentParser(prog="newsfeed", description="ScamRead cyber news feed")
    sub = parser.add_subparsers(dest="command", required=True)
    run_cmd = sub.add_parser("run", help="fetch, curate and write the JSON files once")
    run_cmd.add_argument("--out", type=Path, default=Path("site"), help="output folder (default: site)")
    run_cmd.add_argument("--sources", type=Path, default=config.SOURCES_FILE, help="sources.json to use")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.command == "run":
        status = run(args.out, sources_file=args.sources)
        summary = {k: status[k] for k in ("mode", "fetched_items", "new_items", "curated_items",
                                          "kept_items", "new_stories", "merged_sources")}
        summary["failed_sources"] = [s["name"] for s in status["sources"] if not s["ok"]]
        summary["errors"] = status["errors"]
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
