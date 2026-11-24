"""Fetch RSS/Atom feeds and turn their entries into clean, de-duplicated items."""

from __future__ import annotations

import calendar
import hashlib
import html
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import requests

from . import config

log = logging.getLogger(__name__)

TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "igshid"}
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
REDDIT_LINK_RE = re.compile(r'<a href="([^"]+)">\s*\[link\]\s*</a>', re.IGNORECASE)
REDDIT_BYLINE_RE = re.compile(r"submitted by|\[link\]|\[comments\]|(?<![\w/])/?u/[A-Za-z0-9_-]+", re.IGNORECASE)


@dataclass
class RawItem:
    id: str
    source: str
    source_type: str
    title: str
    url: str
    published: str  # ISO 8601, UTC
    snippet: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SourceResult:
    name: str
    ok: bool
    items: int = 0
    error: Optional[str] = None


def canonical_url(url: str) -> str:
    """Drop tracking parameters and fragments so the same article gets the same id."""
    parts = urlsplit(url.strip())
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS
    ]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(query), ""))


def item_id(url: str) -> str:
    return hashlib.sha1(canonical_url(url).encode("utf-8")).hexdigest()[:16]


def clean_text(value: str, limit: int = 700) -> str:
    text = html.unescape(TAG_RE.sub(" ", value or ""))
    text = SPACE_RE.sub(" ", text).strip()
    return text[:limit].rstrip()


def _entry_time(entry) -> Optional[datetime]:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            return datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc)
    return None


def _entry_html(entry) -> str:
    if entry.get("content"):
        return entry["content"][0].get("value", "")
    return entry.get("summary", "")


def _is_http(url: str) -> bool:
    return urlsplit(url).scheme in ("http", "https")


def parse_feed(source: dict, content: bytes, now: datetime,
               max_age_hours: int = config.MAX_AGE_HOURS,
               max_items: int = config.MAX_ITEMS_PER_SOURCE) -> list[RawItem]:
    """Parse one feed's bytes into RawItems, keeping only recent, well-formed entries."""
    parsed = feedparser.parse(content)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"could not parse feed: {parsed.get('bozo_exception')}")

    cutoff = now - timedelta(hours=max_age_hours)
    items: list[RawItem] = []
    for entry in parsed.entries:
        title = clean_text(entry.get("title", ""), 300)
        link = (entry.get("link") or "").strip()
        published = _entry_time(entry)
        if not title or not link or not _is_http(link) or published is None:
            continue
        if published < cutoff or published > now + timedelta(hours=1):
            continue

        raw_html = _entry_html(entry)
        text = clean_text(raw_html, 5000)
        name = source["name"]
        if source.get("type") == "reddit":
            match = REDDIT_LINK_RE.search(raw_html)
            external = html.unescape(match.group(1)) if match else ""
            if external and _is_http(external) and "reddit.com" not in urlsplit(external).netloc:
                link = external
                name = f"{urlsplit(external).netloc.removeprefix('www.')} via {source['name']}"
            text = REDDIT_BYLINE_RE.sub(" ", text)  # no Reddit usernames in what we store or send

        items.append(RawItem(
            id=item_id(link),
            source=name,
            source_type=source.get("type", "news"),
            title=title,
            url=link,
            published=published.isoformat(timespec="seconds"),
            snippet=clean_text(text),
        ))
        if len(items) >= max_items:
            break
    return items


def http_fetch(url: str) -> bytes:
    response = requests.get(
        url,
        headers={"User-Agent": config.USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"},
        timeout=config.FETCH_TIMEOUT,
    )
    response.raise_for_status()
    return response.content


def fetch_all(sources: list[dict], now: Optional[datetime] = None,
              fetch: Callable[[str], bytes] = http_fetch) -> tuple[list[RawItem], list[SourceResult]]:
    """Fetch every source in parallel. A failing source is reported, never fatal."""
    now = now or datetime.now(timezone.utc)

    def one(source: dict) -> tuple[list[RawItem], SourceResult]:
        try:
            items = parse_feed(source, fetch(source["url"]), now)
            return items, SourceResult(source["name"], True, len(items))
        except Exception as exc:  # network errors, HTTP errors, bad XML
            log.warning("source %s failed: %s", source["name"], exc)
            return [], SourceResult(source["name"], False, 0, f"{type(exc).__name__}: {str(exc)[:200]}")

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(one, sources))

    items: list[RawItem] = []
    seen_ids: set[str] = set()
    for source_items, _ in results:
        for item in source_items:
            if item.id not in seen_ids:
                seen_ids.add(item.id)
                items.append(item)
    return items, [status for _, status in results]
