# Thesis Agent

A deal-intelligence engine a fund points at its own thesis. One YAML file
describes what you invest in; every Monday the agents keep a tracker of
companies true, look for new ones, and publish a dated edition that
[the Observatory](https://observatory.lachlansear.com) draws as a map.

The rule that runs through it: **the model proposes, the source decides.**
A new round, an exit or a shutdown is written to the tracker only if the page
it cites names the company and states the amount or the acquirer. Anything
else is held for a person, with the reason.

---

## How a week runs

```
config/thesis.yaml  ──►  refresh ──► source check ──► data/companies.json ──┐
 (your orbits,           (each          (page must                          │
  rubric, signals,        company:        name the company                   ├─► publish ──► data/observatory.json ──► Observatory
  portfolio to hide)      round? exit?    and the figure)                    │               data/editions/<date>.json
                          shutdown?)          │                              │
                                              └──► data/review.json (held)   │
                     scout ─► score on your rubric ─► data/candidates.json ──┘  (an inbox: never auto-added)
                     radar, ops, events ─► outputs/weekly/*.md
```

| Stage | What it does |
|---|---|
| **Refresh** | For every tracked company (unchecked first, then stalest), Claude searches for events since its last check and cites a page for each. `shared/verify.py` fetches that page and applies the change only if it names the company and states the amount (or the acquirer, or a shutdown). |
| **Scout** | Pulls candidates from thesis-shaped web searches and free sources (Hacker News, RSS, Companies House, GitHub, Product Hunt, Reddit, patents, podcasts, Adzuna, X), de-duplicates against the tracker and past runs, and scores each on *your* rubric with *your* lenses. Track and watch picks go to `data/candidates.json` for a person to review. |
| **Radar** | Rounds, exits and rule changes across your sectors, plus a weekly synthesis. |
| **Ops** | Tracker freshness and cross-references with Radar. |
| **Events** | Conferences, hearings and launches that give a reason to call this week. |
| **Publish** | Writes `data/observatory.json` (minus anything in `exclude_from_views`) and a dated edition. |

The workflow is `.github/workflows/weekly.yml`: Mondays 06:17 UTC, or by hand
from the Actions tab (with a "refresh only" option). It commits the edition, so
the history of every change is in git. `ci.yml` runs the tests, the thesis
check and a dry run on every push.

## Make it yours

1. Fork or "Use this template".
2. Add one model key under Settings → Secrets and variables → Actions:
   `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` or `OPENROUTER_API_KEY`. The engine uses
   whichever is set (or set the repository variable `THESIS_PROVIDER`). Optional keys
   widen the free sources: `COMPANIES_HOUSE_API_KEY`,
   `ADZUNA_APP_ID`/`ADZUNA_APP_KEY`, `PRODUCTHUNT_TOKEN`.
3. Rewrite `config/thesis.yaml`: your belief, your **sectors** (they become the
   orbits and the search lanes), signals, rubric and weights, the lenses the
   scorer applies, and `exclude_from_views` (your own portfolio, so the tool
   never scores or comments on it).
4. Empty `data/companies.json` to `[]`, or seed it with the companies you
   already follow (`python main.py check` tells you what's missing).
5. Run the workflow once by hand. Point a copy of the Observatory at your
   fork's `data/observatory.json` (its README says how).

`examples/theses/sports-tech.yaml` is a deliberately different thesis; swap it
in and the searches, the scoring dimensions and the map all change with it.
The briefs in `examples/sports-tech-briefs/` came from it.

## The reference instance

`config/thesis.yaml` is Lachlan Sear's thesis, **Permission to operate**: the
durable AI companies sell where the bottleneck is permission, not the model.
Four orbits:

- regulated vertical AI;
- defence and dual-use;
- robotics and autonomy;
- AI assurance, the evaluation, security and certification layer the other three must pass through.

Edition 1 (13 October 2026) was checked by hand: all 31 companies, and every
round and exit in it (29 of 29) passes the same source check the weekly run
uses. Weekly runs take over from Monday 19 October.

## Run it locally

```bash
pip install -r requirements.txt
cp .env.example .env                 # add one model key
python main.py check                 # validate the thesis and the tracker
python main.py weekly --dry-run      # the whole pipeline, no API calls
python main.py run --refresh --limit 5
python main.py weekly                # the real thing
python main.py publish               # rebuild data/observatory.json
python -m pytest -q tests
```

## Providers

| Provider | Key | Web search | Defaults (fast / deep) |
|---|---|---|---|
| Anthropic | `ANTHROPIC_API_KEY` | Claude's web search tool | `claude-sonnet-5-5` / `claude-opus-5-5` |
| OpenAI | `OPENAI_API_KEY` | Responses API `web_search` | `gpt-5-mini` / `gpt-5` |
| OpenRouter | `OPENROUTER_API_KEY` | the `web` plugin, any model | `anthropic/claude-sonnet-4.5` / `anthropic/claude-opus-4.1` |

Pin models with `THESIS_MODEL_FAST` and `THESIS_MODEL_DEEP` (environment or
repository variables). The source check is the same for all three. One
difference: when a cited page can't be fetched, Anthropic and OpenRouter can
still be checked against the passage they retrieved from it. OpenAI returns
only the link, so its paywalled finds are held for review.

## Files

```
config/thesis.yaml          the thesis (the only file a fund edits)
data/companies.json         the tracker: public fields only, every figure with a source
data/observatory.json       what the Observatory reads
data/editions/              one file per run: what changed and why
data/review.json            changes held because their source didn't support them
data/candidates.json        Scout's inbox
agents/refresh/             the weekly refresh
shared/verify.py            the source check
shared/publish.py           edition and observatory.json
```

## Limits, plainly

- The source check is textual. It confirms that the cited page names the company
  and states the figure; it can't tell whether the page is right. Low-quality
  sources are possible, so each one is shown on the map.
- Paywalled pages can't be fetched. The check then falls back to the passage
  the search tool retrieved from that page (Anthropic, OpenRouter), never to
  the model's own sentence.
- Capital is converted to dollars at fixed approximate rates, for placing dots
  on the map only. Figures are always shown as reported.
- Sources that need a key are skipped without one, and the brief says which ran.

MIT licence.
