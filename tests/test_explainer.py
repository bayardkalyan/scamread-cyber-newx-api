import json
from types import SimpleNamespace

from newsfeed import pipeline
from newsfeed.explainer import Explainer, clean_concept
from tests.test_pipeline import NOW, FakeCurator, fake_fetch, write_sources

STORY = {"story_key": "k1", "headline": "Card-stealing code hit 178 websites", "summary": "Attackers hijacked a vendor script.", "category": "data-breach"}


class FakeExplainer:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def explain(self, stories):
        self.calls.append([s["story_key"] for s in stories])
        if self.fail:
            raise RuntimeError("API down")
        return {
            s["story_key"]: {
                "title": "What is a supply-chain attack?",
                "points": [
                    "Instead of breaking into a website directly, attackers break into a company that supplies it with code.",
                    "The bad code then reaches every website that uses that supplier, like poison in a shared water tank.",
                ],
            }
            for s in stories
        }


def test_clean_concept_rules():
    good = {"needed": True, "title": " What is   phishing? ", "points": ["One.", "Two.", "Three.", "Four."]}
    out = clean_concept(good, STORY)
    assert out == {"title": "What is phishing?", "points": ["One.", "Two.", "Three."]}
    assert clean_concept({"needed": False, "title": "", "points": []}, STORY) is None
    assert clean_concept({"needed": True, "title": "Only one point", "points": ["One."]}, STORY) is None
    assert clean_concept({"needed": True, "title": "", "points": ["a", "b"]}, STORY) is None
    assert clean_concept({"needed": True, "title": "Что это?", "points": ["a", "b"]}, STORY) is None


def test_explainer_sends_schema_and_parses():
    sent = {}

    class Msgs:
        def create(self, **kw):
            sent.update(kw)
            body = {"results": [
                {"key": "k1", "needed": True, "title": "What is a supply-chain attack?", "points": ["Point one.", "Point two."]},
                {"key": "unknown", "needed": True, "title": "x", "points": ["a", "b"]},
            ]}
            return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(body))], usage=None)

    out = Explainer(client=SimpleNamespace(messages=Msgs())).explain([STORY])
    assert out == {"k1": {"title": "What is a supply-chain attack?", "points": ["Point one.", "Point two."]}}
    assert sent["output_config"]["format"]["type"] == "json_schema"
    assert "<stories>" in sent["messages"][0]["content"] and "beginners" in sent["system"]


def test_run_adds_concepts_once(tmp_path):
    site = tmp_path / "site"
    explainer = FakeExplainer()
    status = pipeline.run(site, sources_file=write_sources(tmp_path), curator=FakeCurator(),
                          explainer=explainer, fetch=fake_fetch, now=NOW)
    assert status["explained_stories"] == 1
    item = json.loads((site / "feed.json").read_text())["items"][0]
    assert item["concept"]["title"] == "What is a supply-chain attack?"
    assert len(item["concept"]["points"]) == 2
    assert "concept_checked" not in item  # internal flag stays private

    again = FakeExplainer()
    pipeline.run(site, sources_file=write_sources(tmp_path), curator=FakeCurator(), explainer=again, fetch=fake_fetch, now=NOW)
    assert again.calls == []  # already explained, no second Claude call


def test_explainer_failure_is_retried_and_feed_still_publishes(tmp_path):
    site = tmp_path / "site"
    status = pipeline.run(site, sources_file=write_sources(tmp_path), curator=FakeCurator(),
                          explainer=FakeExplainer(fail=True), fetch=fake_fetch, now=NOW)
    assert any(e.startswith("explainer:") for e in status["errors"])
    item = json.loads((site / "feed.json").read_text())["items"][0]
    assert "concept" not in item
    retry = FakeExplainer()
    status2 = pipeline.run(site, sources_file=write_sources(tmp_path), curator=FakeCurator(), explainer=retry, fetch=fake_fetch, now=NOW)
    assert retry.calls and status2["explained_stories"] == 1
