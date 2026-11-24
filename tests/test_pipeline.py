import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from newsfeed import pipeline
from newsfeed.curator import Curator, CurationError, validate_results
from newsfeed.fetcher import canonical_url, fetch_all, parse_feed

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 24, 7, 0, tzinfo=timezone.utc)
SOURCES = [
    {"name": "Example News", "url": "https://news.example.com/feed", "type": "news"},
    {"name": "r/netsec", "url": "https://www.reddit.com/r/netsec/top/.rss", "type": "reddit"},
    {"name": "Broken Source", "url": "https://broken.example.com/feed", "type": "news"},
    {"name": "Switched Off", "url": "https://off.example.com/feed", "type": "news", "enabled": False},
]


def fake_fetch(url: str) -> bytes:
    if "news.example.com" in url:
        return (FIXTURES / "news.xml").read_bytes()
    if "reddit.com" in url:
        return (FIXTURES / "reddit.xml").read_bytes()
    raise ConnectionError("simulated outage")


class FakeCurator:
    """Mimics Claude: keeps the attack stories as one story, drops jobs and Reddit questions."""

    def __init__(self):
        self.calls = []

    def curate(self, items, recent):
        self.calls.append(([i.id for i in items], recent))
        results = []
        for i in items:
            news = "178" in i.title
            results.append({
                "id": i.id, "keep": news,
                "headline": "Card-stealing code hit 178 websites" if news else "",
                "summary": "Attackers hijacked a testing vendor's scripts." if news else "",
                "category": "data-breach" if news else "other",
                "importance": 9 if i.source_type == "news" else 7,
                "story_key": "optimizely-supply-chain-attack" if news else f"drop-{i.id}",
            })
        return validate_results(results, items)


def write_sources(tmp_path):
    path = tmp_path / "sources.json"
    path.write_text(json.dumps({"sources": SOURCES}))
    return path


def test_canonical_url_strips_tracking():
    assert canonical_url("https://A.com/x?utm_source=rss&id=5#top") == "https://a.com/x?id=5"


def test_parse_feed_filters_old_and_unsafe_items():
    items = parse_feed(SOURCES[0], (FIXTURES / "news.xml").read_bytes(), NOW)
    titles = [i.title for i in items]
    assert "Old story that should be ignored" not in titles
    assert "Item with a javascript link" not in titles
    assert len(items) == 2
    assert "<b>" not in items[0].snippet


def test_reddit_uses_external_link_and_hides_usernames():
    items = parse_feed(SOURCES[1], (FIXTURES / "reddit.xml").read_bytes(), NOW)
    first = items[0]
    assert first.url == "https://research.example.org/optimizely-writeup"
    assert first.source == "research.example.org via r/netsec"
    assert "/u/someone" not in first.snippet
    assert items[1].url.startswith("https://www.reddit.com/")  # self post keeps reddit link


def test_fetch_all_survives_a_broken_source():
    items, results = fetch_all(SOURCES, now=NOW, fetch=fake_fetch)
    by_name = {r.name: r for r in results}
    assert by_name["Broken Source"].ok is False
    assert by_name["Example News"].ok is True
    assert len(items) == 4


def test_full_run_merges_sources_and_writes_files(tmp_path):
    curator = FakeCurator()
    status = pipeline.run(tmp_path / "site", sources_file=write_sources(tmp_path),
                          curator=curator, fetch=fake_fetch, now=NOW)
    site = tmp_path / "site"
    feed = json.loads((site / "feed.json").read_text())
    top = json.loads((site / "top.json").read_text())

    assert status["new_stories"] == 1
    assert status["merged_sources"] == 1
    assert feed["count"] == 1
    story = feed["items"][0]
    assert story["headline"] == "Card-stealing code hit 178 websites"
    assert story["importance"] == 9
    assert {s["name"] for s in story["sources"]} == {"Example News", "research.example.org via r/netsec"}
    assert top["items"][0]["id"] == story["id"]
    assert (site / "status.json").exists()

    # Second run: nothing new, so Claude is not called again.
    curator2 = FakeCurator()
    status2 = pipeline.run(site, sources_file=write_sources(tmp_path), curator=curator2, fetch=fake_fetch, now=NOW)
    assert curator2.calls == []
    assert status2["new_items"] == 0
    assert json.loads((site / "feed.json").read_text())["count"] == 1


def test_failed_batch_is_retried_next_run(tmp_path):
    class Boom:
        def curate(self, items, recent):
            raise CurationError("simulated")

    status = pipeline.run(tmp_path / "site", sources_file=write_sources(tmp_path), curator=Boom(),
                          fetch=fake_fetch, now=NOW)
    assert status["errors"]
    assert json.loads((tmp_path / "site" / "state" / "seen.json").read_text()) == {}
    status2 = pipeline.run(tmp_path / "site", sources_file=write_sources(tmp_path), curator=FakeCurator(),
                           fetch=fake_fetch, now=NOW)
    assert status2["new_stories"] == 1


def test_fetch_only_mode_without_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    status = pipeline.run(tmp_path / "site", sources_file=write_sources(tmp_path), fetch=fake_fetch, now=NOW)
    assert status["mode"] == "fetch-only"
    assert not (tmp_path / "site" / "feed.json").exists()


def test_validate_results_cleans_bad_output():
    from newsfeed.fetcher import RawItem
    item = RawItem("abc", "S", "news", "T", "https://x.com", NOW.isoformat(), "s")
    cleaned = validate_results([
        {"id": "abc", "keep": True, "headline": "H", "summary": "S", "category": "RANSOMWARE",
         "importance": 99, "story_key": "Big Story!!"},
        {"id": "unknown", "keep": True, "headline": "x", "summary": "y", "category": "other",
         "importance": 5, "story_key": "z"},
    ], [item])
    assert len(cleaned) == 1
    assert cleaned[0]["category"] == "ransomware"
    assert cleaned[0]["importance"] == 10
    assert cleaned[0]["story_key"] == "big-story"


def test_curator_sends_schema_and_parses_response():
    from newsfeed.fetcher import RawItem
    item = RawItem("abc", "S", "news", "Title", "https://x.com", NOW.isoformat(), "snippet")
    sent = {}

    class FakeMessages:
        def create(self, **kwargs):
            sent.update(kwargs)
            body = {"items": [{"id": "abc", "keep": True, "headline": "H", "summary": "S",
                               "category": "malware", "importance": 6, "story_key": "k"}]}
            return SimpleNamespace(stop_reason="end_turn",
                                   content=[SimpleNamespace(type="text", text=json.dumps(body))],
                                   usage=SimpleNamespace(input_tokens=10, output_tokens=5))

    curator = Curator(client=SimpleNamespace(messages=FakeMessages()), model="claude-haiku-5-5")
    out = curator.curate([item], [])
    assert out[0]["headline"] == "H"
    assert sent["output_config"]["format"]["type"] == "json_schema"
    assert sent["model"] == "claude-haiku-5-5"
    assert "<items>" in sent["messages"][0]["content"]


def test_curator_raises_on_truncated_output():
    from newsfeed.fetcher import RawItem
    item = RawItem("abc", "S", "news", "Title", "https://x.com", NOW.isoformat(), "snippet")

    class FakeMessages:
        def create(self, **kwargs):
            return SimpleNamespace(stop_reason="max_tokens", content=[], usage=None)

    with pytest.raises(CurationError):
        Curator(client=SimpleNamespace(messages=FakeMessages())).curate([item], [])


def test_disabled_sources_are_skipped(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    status = pipeline.run(tmp_path / "site", sources_file=write_sources(tmp_path), fetch=fake_fetch, now=NOW)
    assert "Switched Off" not in [s["name"] for s in status["sources"]]


def test_api_key_cleanup_and_description():
    fake = "sk-ant-usr-1_" + "x" * 60
    raw = f'  "{fake}\n'
    assert pipeline.clean_api_key(raw) == fake
    desc = pipeline.describe_api_key(raw)
    assert "xxxx" not in desc and "looks like a Claude API key: True" in desc
    assert "looks like a Claude API key: False" in pipeline.describe_api_key("scamre")
    assert "had extra spaces or line breaks: True" in desc


def test_rejected_key_stops_after_first_batch(tmp_path, monkeypatch):
    class AuthError(Exception):
        status_code = 401

    class Rejecting:
        calls = 0
        def curate(self, items, recent):
            Rejecting.calls += 1
            raise AuthError("Invalid bearer token")

    monkeypatch.setattr(pipeline.config, "BATCH_SIZE", 1)
    status = pipeline.run(tmp_path / "site", sources_file=write_sources(tmp_path), curator=Rejecting(),
                          fetch=fake_fetch, now=NOW)
    assert Rejecting.calls == 1
    assert any("rejected" in e for e in status["errors"])
