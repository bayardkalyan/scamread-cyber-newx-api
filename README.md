# ScamRead Cyber News API

An open-source cybersecurity news feed. Every 30 minutes it reads trusted security news sites and Reddit, has Claude write a short, original headline and summary for each real story, groups different reports of the same story together, and publishes the result as JSON. A WordPress plugin is included to show the feed on any site.

Built for [scamread.com](https://scamread.com).

```
 News sites (RSS) ─┐
                   ├─► fetch ─► new items only ─► Claude curates ─► feed.json / top.json ─► WordPress plugin
 Reddit (RSS)     ─┘            (deduplicated)    (headline, summary,   (GitHub Pages)       [scamread_news]
                                                   category, importance)
```

Everything runs on GitHub for free: GitHub Actions does the work and GitHub Pages serves the JSON. No server needed.

## The API

Base URL: `https://bayardkalyan.github.io/scamread-cyber-newx-api/`

| File | What it holds |
|---|---|
| `feed.json` | Latest 60 stories, newest first |
| `top.json` | Top 5 stories of the last 24 hours, most important first |
| `status.json` | What happened on the last run: which sources worked, how many items, any errors |
| `index.html` | A simple page that shows the feed |

Each story looks like this:

```json
{
  "id": "3f1c2a9b8e7d",
  "headline": "Card-stealing code hit 178 websites through testing vendor",
  "summary": "Attackers hijacked Optimizely's scripts, so code that stole card details and cookies ran on big sites including Zoom and the BBC.",
  "category": "data-breach",
  "importance": 9,
  "published": "2026-11-16T14:02:00+00:00",
  "updated": "2026-11-17T08:37:00+00:00",
  "sources": [
    {"name": "BleepingComputer", "url": "https://www.bleepingcomputer.com/...", "published": "..."},
    {"name": "The Hacker News", "url": "https://thehackernews.com/...", "published": "..."}
  ]
}
```

Categories: `data-breach`, `scam-phishing`, `vulnerability`, `ransomware`, `malware`, `ai-security`, `privacy-policy`, `other`.

## Setup (one time)

1. **Add your Claude API key.** In this repo: Settings → Secrets and variables → Actions → New repository secret. Name: `ANTHROPIC_API_KEY`. Value: your key from [platform.claude.com](https://platform.claude.com). Never paste the key anywhere else.
2. **Run it once.** Actions tab → "Update news feed" → Run workflow. After about a minute, open the base URL above. From then on it runs by itself every 30 minutes.
3. **Install the WordPress plugin.** Download [`dist/scamread-news-feed.zip`](dist/scamread-news-feed.zip), then in WordPress: Plugins → Add New → Upload Plugin → Activate. Add a Shortcode block with `[scamread_news]` to any page.

Without the API key, runs still fetch the sources and write `status.json` (handy for checking sources), but don't publish stories.

## WordPress shortcode

| Shortcode | Shows |
|---|---|
| `[scamread_news]` | Latest 20 stories |
| `[scamread_news view="top" limit="5" title="Today's top 5"]` | Top stories of the last 24 hours |
| `[scamread_news category="scam-phishing" limit="10"]` | One category only |
| `[scamread_news style="live" limit="6" title="Happening right now" refresh="120" more="/cyber-news/"]` | Live feed: pulsing LIVE badge, timeline, stories pop in on load, new ones slide in with a NEW tag |
| `refresh="300"` | How often (seconds) the list refreshes itself while the page is open; `0` turns it off |

The plugin fetches the feed on the server, caches it for 5 minutes and keeps the last working copy if GitHub is ever unreachable. Visitors' browsers only talk to your WordPress site. Settings → ScamRead News shows whether the feed is working.

## Sources

Listed in [`newsfeed/sources.json`](newsfeed/sources.json): The Hacker News, BleepingComputer, SecurityWeek, Krebs on Security, Dark Reading, The Record, Help Net Security, Cyber Security News and CISA. Add any site with an RSS or Atom feed by adding a line. A source that fails is skipped and reported in `status.json`; the others carry on.

**Reddit** (r/netsec, r/cybersecurity) is in the list but switched off (`"enabled": false`): Reddit blocks requests from GitHub's servers. It can be switched on if the feed ever runs from a different server.

**X (Twitter)** is not included. Its API charges per post read, so following accounts adds a running cost; it can be added later as a paid option.

## What Claude does (and doesn't)

- Keeps only real security news. Drops job posts, webinars, adverts and Reddit questions.
- Writes the headline and summary in its own words from the article's title and RSS snippet only. It never sees or copies full articles.
- Groups reports of the same story from different sites into one story with several source links.
- Treats everything it reads as untrusted data, so instructions hidden in an article can't steer it.
- Uses Claude Haiku 5.5 with structured outputs, so the response always matches the expected JSON shape.

Every story links to the original reports. The summaries are AI-written; the original articles are the authority.

## Cost

GitHub Actions and Pages are free for public repositories. Claude costs depend on how much news there is; with Haiku and only new items sent, expect a few dollars a month at most. Set a monthly spend limit in the Claude Console to be safe.

## Run it locally

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...        # optional: without it you get a fetch-only run
python -m newsfeed run --out site   # writes site/feed.json, site/top.json, site/status.json
pip install pytest && python -m pytest
```

Settings can be changed with environment variables, for example `NEWSFEED_MODEL`, `NEWSFEED_MAX_AGE_HOURS`, `NEWSFEED_FEED_LIMIT`. See [`newsfeed/config.py`](newsfeed/config.py).

## Notes

- GitHub may pause scheduled workflows on public repos that go 60 days without activity. If the feed stops updating, open the Actions tab and re-enable the workflow.
- Scheduled runs can start a few minutes late when GitHub is busy.

## License

MIT
