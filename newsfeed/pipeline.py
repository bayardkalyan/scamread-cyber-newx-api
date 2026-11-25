"""One run: fetch new items, curate them, merge into stories, write the public JSON files.

Files written to the output folder:
  feed.json          latest stories, newest first (what the website shows)
  top.json           top stories of the last 24 hours, most important first
  status.json        what happened on the last run (sources ok/failed, counts, errors)
  state/seen.json    ids of items already processed, so Claude never sees them twice
  state/stories.json every story from the last 7 days (the working store)
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from . import __version__, config
from .curator import CATEGORIES, Curator
from .explainer import Explainer
from .fetcher import RawItem, fetch_all, http_fetch
from .store import load_json, save_json

log = logging.getLogger(__name__)


def _parse(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _chunks(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def clean_api_key(raw: str) -> str:
    """Remove spaces, line breaks and stray quotes that sneak in when a key is copied."""
    return "".join(raw.split()).strip("'\"")


def describe_api_key(raw: str) -> str:
    """Describe the key's shape without revealing any of it (Actions logs are public)."""
    key = clean_api_key(raw)
    return (f"length {len(key)}, looks like a Claude API key: {key.startswith('sk-ant-') and len(key) > 40}, "
            f"had extra spaces or line breaks: {key != raw}")


def merge_results(stories: dict[str, dict], results: list[dict], items: list[RawItem], now: datetime) -> tuple[int, int]:
    """Add curated results to the story store. Returns (new_stories, merged_sources)."""
    by_id = {i.id: i for i in items}
    new_count = merged = 0
    for r in results:
        if not r["keep"]:
            continue
        item = by_id[r["id"]]
        source = {"name": item.source, "url": item.url, "published": item.published}
        story = stories.get(r["story_key"])
        if story is None:
            stories[r["story_key"]] = {
                "id": hashlib.sha1(r["story_key"].encode()).hexdigest()[:12],
                "story_key": r["story_key"],
                "headline": r["headline"],
                "summary": r["summary"],
                "category": r["category"],
                "importance": r["importance"],
                "published": item.published,
                "first_seen": _iso(now),
                "updated": _iso(now),
                "sources": [source],
            }
            new_count += 1
        elif all(s["url"] != item.url and s["name"] != item.source for s in story["sources"]):
            story["sources"].append(source)
            story["importance"] = max(story["importance"], r["importance"])
            if _parse(item.published) < _parse(story["published"]):
                story["published"] = item.published
            story["updated"] = _iso(now)
            merged += 1
    return new_count, merged


def public_story(story: dict) -> dict:
    keys = ("id", "headline", "summary", "category", "importance", "published", "updated", "sources")
    out = {k: story[k] for k in keys}
    if story.get("concept"):
        out["concept"] = story["concept"]  # "Learn the concept": {"title", "points"}
    return out


def add_concepts(stories: list[dict], explainer: Explainer, status: dict,
                 limit: int = config.EXPLAIN_MAX_PER_RUN, batch_size: int = config.EXPLAIN_BATCH_SIZE) -> None:
    """Write beginner explainers for the newest stories not looked at yet."""
    todo = [s for s in stories if not s.get("concept_checked")][:limit]
    for batch in _chunks(todo, batch_size):
        try:
            concepts = explainer.explain(batch)
        except Exception as exc:  # stories stay unchecked, so the next run tries again
            log.error("explainer failed for a batch of %d: %s", len(batch), exc)
            status["errors"].append(f"explainer: {type(exc).__name__}: {str(exc)[:200]}")
            if getattr(exc, "status_code", None) in (401, 403):
                break
            continue
        for story in batch:
            if story["story_key"] in concepts:
                story["concept"] = concepts[story["story_key"]]
                story["concept_checked"] = True
                if story["concept"]:
                    status["explained_stories"] += 1


def build_top(stories: list[dict], now: datetime, window_hours: int, n: int) -> list[dict]:
    """Most important stories in the window; widen to 48h if the window is too quiet."""
    for hours in (window_hours, max(window_hours, 48)):
        cutoff = now - timedelta(hours=hours)
        recent = [s for s in stories if _parse(s["published"]) >= cutoff]
        if len(recent) >= n or hours >= 48:
            break
    # More sources covering a story is a signal it matters, so use it as a tie-breaker.
    recent.sort(key=lambda s: (s["importance"], len(s["sources"]), s["published"]), reverse=True)
    return recent[:n]


def run(out_dir: Path,
        sources_file: Path = config.SOURCES_FILE,
        curator: Optional[Curator] = None,
        explainer: Optional[Explainer] = None,
        fetch: Callable[[str], bytes] = http_fetch,
        now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    out_dir = Path(out_dir)
    state_dir = out_dir / "state"

    seen: dict[str, str] = load_json(state_dir / "seen.json", {})
    stories: dict[str, dict] = {s["story_key"]: s for s in load_json(state_dir / "stories.json", {"stories": []})["stories"]}
    for story in stories.values():  # one link per outlet
        unique: dict[str, dict] = {}
        for src in story["sources"]:
            unique.setdefault(src["name"], src)
        story["sources"] = list(unique.values())
    sources = [s for s in load_json(Path(sources_file), {"sources": []})["sources"] if s.get("enabled", True)]

    items, source_results = fetch_all(sources, now=now, fetch=fetch)
    new_items = sorted((i for i in items if i.id not in seen), key=lambda i: i.published, reverse=True)
    pending = len(new_items)
    new_items = new_items[:config.MAX_NEW_PER_RUN]

    status = {
        "version": __version__,
        "run_at": _iso(now),
        "mode": "full",
        "sources": [vars(s) for s in source_results],
        "fetched_items": len(items),
        "new_items": pending,
        "curated_items": 0,
        "kept_items": 0,
        "new_stories": 0,
        "merged_sources": 0,
        "explained_stories": 0,
        "errors": [],
    }

    api_key = clean_api_key(os.environ.get("ANTHROPIC_API_KEY", ""))
    if curator is None and api_key:
        log.info("API key check: %s", describe_api_key(os.environ.get("ANTHROPIC_API_KEY", "")))
        curator = Curator(api_key=api_key)
        if explainer is None:
            explainer = Explainer(api_key=api_key)
    if curator is None:
        status["mode"] = "fetch-only"
        status["errors"].append("ANTHROPIC_API_KEY is not set: fetched sources but did not curate.")
        save_json(out_dir / "status.json", status)
        log.warning("No ANTHROPIC_API_KEY, fetch-only run: %d new items waiting", pending)
        return status

    for batch in _chunks(new_items, config.BATCH_SIZE):
        cutoff = now - timedelta(hours=48)
        recent = sorted((s for s in stories.values() if _parse(s["published"]) >= cutoff),
                        key=lambda s: s["published"], reverse=True)[:80]
        try:
            results = curator.curate(batch, recent)
        except Exception as exc:  # leave these items unseen so the next run retries them
            log.error("curation failed for a batch of %d: %s", len(batch), exc)
            status["errors"].append(f"{type(exc).__name__}: {str(exc)[:300]}")
            if getattr(exc, "status_code", None) in (401, 403):
                status["errors"].append(
                    "The Claude API key was rejected. Create a new key at platform.claude.com/settings/keys "
                    "and replace the ANTHROPIC_API_KEY secret in this repo.")
                break  # same key for every batch, so stop instead of failing each one
            continue
        new_count, merged = merge_results(stories, results, batch, now)
        status["curated_items"] += len(batch)
        status["kept_items"] += sum(1 for r in results if r["keep"])
        status["new_stories"] += new_count
        status["merged_sources"] += merged
        for item in batch:
            seen[item.id] = _iso(now)

    # Prune old data
    story_cutoff = now - timedelta(days=config.STORY_RETENTION_DAYS)
    stories = {k: s for k, s in stories.items() if _parse(s["published"]) >= story_cutoff}
    seen_cutoff = now - timedelta(days=config.SEEN_RETENTION_DAYS)
    seen = {k: v for k, v in seen.items() if _parse(v) >= seen_cutoff}

    ordered = sorted(stories.values(), key=lambda s: s["published"], reverse=True)
    key_rejected = any("API key was rejected" in e for e in status["errors"])
    if explainer is not None and not key_rejected:
        add_concepts(ordered[:config.FEED_LIMIT], explainer, status)
    updated_at = _iso(now)
    meta = {
        "name": "ScamRead cyber news feed",
        "updated_at": updated_at,
        "note": "Headlines and summaries are written by AI (Claude) from the original reports. Follow the source links for the full articles.",
        "categories": CATEGORIES,
    }
    save_json(state_dir / "seen.json", seen)
    save_json(state_dir / "stories.json", {"updated_at": updated_at, "stories": ordered})
    save_json(out_dir / "feed.json", {**meta, "count": min(len(ordered), config.FEED_LIMIT),
                                      "items": [public_story(s) for s in ordered[:config.FEED_LIMIT]]})
    top = build_top(ordered, now, config.TOP_WINDOW_HOURS, config.TOP_N)
    save_json(out_dir / "top.json", {**meta, "window_hours": config.TOP_WINDOW_HOURS, "count": len(top),
                                     "items": [public_story(s) for s in top]})
    save_json(out_dir / "status.json", status)

    if config.TEMPLATE_DIR.is_dir():
        for path in config.TEMPLATE_DIR.iterdir():
            if path.is_file():
                shutil.copy2(path, out_dir / path.name)

    log.info("run done: %d new items, %d kept, %d new stories, %d merged sources, %d explained, %d errors",
             status["curated_items"], status["kept_items"], status["new_stories"],
             status["merged_sources"], status["explained_stories"], len(status["errors"]))
    return status
