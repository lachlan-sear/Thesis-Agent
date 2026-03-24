# Thesis Agent

An autonomous deal intelligence system for venture capital.

Three AI agents that source, evaluate, and maintain a deal pipeline against a configurable investment thesis. Built on the principle that deal sourcing is intelligence work — and intelligence work is what AI does best.

---

## The Thesis Behind the Tool

Julien Bek at Sequoia recently argued that the next trillion-dollar company won't sell software tools — it will sell the work itself. For every dollar spent on software, six are spent on services. When AI drives the cost of intelligence work toward zero, the real opportunity is in capturing the labour budget, not the tool budget.

The same logic applies inside a VC fund. Most deal sourcing is pattern matching against a thesis — scanning hundreds of companies to find the handful worth a partner meeting. That's intelligence, not judgement. The judgement is deciding whether to invest.

**thesis-agent automates the intelligence layer.** It sources, evaluates, and maintains a deal pipeline autonomously — surfacing structured recommendations for the human to make judgement calls on. Every improvement in the underlying model makes the sourcing faster, cheaper, and more comprehensive.

The thesis is configurable. Swap in your own `thesis.yaml` and the entire system re-orients: different verticals, different signals, different scoring rubrics.

---

## Architecture

Three agents, one system. Each runs on a schedule and generates actionable reports.

```
┌─────────────────────────────────────────────────────────┐
│                      thesis.yaml                        │
│            (configurable investment thesis)             │
└────────────────────────┬────────────────────────────────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
    ┌───────────┐  ┌───────────┐  ┌───────────┐
    │   SCOUT   │  │   RADAR   │  │    OPS    │
    │  (daily)  │  │  (daily)  │  │  (weekly) │
    │           │  │           │  │           │
    │ 12 sources│  │ Funding   │  │ Staleness │
    │ Dedup     │  │ Exits     │  │ Promotion │
    │ Evaluate  │  │ Trends    │  │ Kill      │
    │ Enrich    │  │ Regulate  │  │ X-ref     │
    └─────┬─────┘  └─────┬─────┘  └─────┬─────┘
          │              │              │
          ▼              ▼              ▼
    Scout Brief     Radar Digest    Ops Review
    (markdown)      (markdown)      (markdown)
```

| Agent | Schedule | What it does |
|-------|----------|--------------|
| **Scout** | Daily | Sources new companies from 12 data sources. Evaluates each against the thesis using 5 VC frameworks (scored 1-10 across 13 dimensions). Enriches top hits with deep research. Outputs a brief with recommendations. |
| **Radar** | Daily + Weekly | Monitors funding rounds, exits, shutdowns, regulatory shifts, and competitive moves across thesis verticals. Tracks investor activity. Weekly synthesis distils signals into thesis implications. |
| **Ops** | Weekly | Audits the tracker for staleness. Checks tracked companies for news and hiring signals. Suggests promotions (to benchmark tier) and kills. Cross-references with radar signals. |

The agents reinforce each other. Scout finds a company → Radar catches a regulatory change in the same vertical → Ops cross-references both and flags the update.

---

## Sample Output

The examples below are from a **Sports Tech** thesis configuration — demonstrating that the system works for any investment thesis, not just the author's. See [examples/](examples/) for the full set.

Here's what a scout brief entry looks like ([full brief](examples/scout_2026-03-23.md)):

> **Arcade** (8.1/10) — AI-powered youth sports video platform. Automates game film analysis for amateur leagues and travel teams.
>
> | Dimension | Score | Notes |
> |-----------|-------|-------|
> | Thesis Fit | **9**/10 | |
> | Customer Durability | **8**/10 | |
> | Regulation Moat | **6**/10 | |
> | Unit Economics | **7**/10 | |
> | Growth Inflection | **8**/10 | |
> | Founder Quality | **7**/10 | |
> | Autopilot Potential | **9**/10 | *Selling the work or the tool?* |
> | Funding & Cap Table | **5**/10 | ~$4M seed |
> | TAM / Market Size | **8**/10 | $30B+ youth sports |
> | Revenue Model | **8**/10 | subscription |
> | Go-to-Market | **7**/10 | viral — team sharing |
> | Geographic Scalability | **7**/10 | |
> | Exit Potential | **7**/10 | Hudl, WSC Sports precedents |
> | **Composite** | **7.6**/10 | |
>
> **Bull case:** Youth sports parents spend $30B+/year in the US alone. Automated game film replaces $500/game human videographers — pure autopilot. Viral distribution through team sharing.
>
> **Bear case:** Low switching costs. No regulatory moat. Hudl dominates at college/pro level and could move downstream.

And here's an ops review recommending a promotion ([full review](examples/ops_2026-03-23.md)):

> **Promote to Benchmark: Playtomic**
> *Tracked since January 2026. Composite: 8.4/10.*
>
> Three signals converging: hiring surge (18 roles on Adzuna), geographic expansion into UK/Germany, and padel participation growing 25% YoY across Europe. Series B likely within 6 months.

The scout scans 12 sources, deduplicates against history, scores every company on 13 dimensions using 5 VC evaluation frameworks, and enriches the top hits with founder backgrounds, competitive landscape, regulatory context, TAM estimates, revenue model analysis, and exit comparables.

---

## 12 Data Sources

The scout agent pulls from 12 sources covering the full company lifecycle — from incorporation to breakout. 11 are free.

| Source | What it catches | When in lifecycle | Cost |
|--------|----------------|-------------------|------|
| **Companies House** | UK incorporations by SIC code | Day 0 — incorporation | Free |
| **Product Hunt** | Product launches | Day 1 — launch | Free |
| **GitHub** | Developer traction (star velocity, contributors) | Weeks 1-12 — adoption | Free |
| **Hacker News** | Builder community signal (Show HN, top stories) | Weeks 1-12 | Free |
| **Reddit** | Practitioner frustration and adoption signals | Ongoing — demand signal | Free |
| **Podcasts** | Founder appearances on 20VC, Riding Unicorns, etc. | Ongoing — fundraise signal | Free |
| **Twitter/X** | Funding announcements, investor activity | Ongoing | Free |
| **RSS Feeds** | Press coverage (Sifted, TechCrunch, EU-Startups) | Ongoing | Free |
| **Adzuna** | Hiring velocity — the #1 breakout predictor | Months 3-12 — pre-funding | Free |
| **USPTO Patents** | IP defensibility signals | Months 6-24 — moat building | Free |
| **Wikipedia** | Mindshare trends (pageview velocity) | Ongoing — awareness | Free |
| **Claude Web Search** | Thesis-targeted queries across 7 signal categories | Anytime — fills gaps | API cost |

Each source is a module implementing `fetch() → list[RawCandidate]`. Add a new source by dropping a file in `agents/scout/sources/`.

---

## Evaluation Frameworks

**Evaluator** — Scores every candidate across 13 dimensions: thesis fit, customer durability, regulation moat, unit economics, growth inflection, founder quality, autopilot potential (Sequoia framework), funding & cap table quality, TAM, revenue model, go-to-market efficiency, geographic scalability, and exit potential. Runs 5 analytical frameworks: moat taxonomy, Sequoia autopilot test, 10x test, founder-market fit, and outsourcing wedge analysis.

The 5 analytical frameworks:

1. **Moat Taxonomy** — regulatory, data, workflow, network, or none
2. **Sequoia Autopilot Test** — selling the work (autopilot) or the tool (copilot)?
3. **10x Test** — 10x better, 10x cheaper, or both?
4. **Founder-Market Fit** — domain expertise, operator background, industry credibility
5. **Outsourcing Wedge** — is the task already outsourced? (Existing budget = clean substitution)

Scoring calibration: 1-3 weak, 4-6 interesting but not meeting-ready, 7+ warrants a partner meeting, 8-9 exceptional, 10 generational.

---

## How It Works

### 1. Define your thesis

Everything flows from `config/thesis.yaml`. It defines target verticals, positive and negative signals, stage and geography focus, evaluation rubric with weighted dimensions, regulatory monitoring queries, and investor activity tracking.

The thesis is fully configurable. A healthcare investor, a fintech fund, a sports tech scout — each swaps in their own config and the entire system re-orients. The examples in this repo use a Sports Tech thesis to demonstrate this.

### 2. Scout sources companies

The scout agent searches across 12 sources in parallel, deduplicates against the SQLite history, evaluates every candidate using Claude against 5 VC frameworks, and enriches high-scorers with deep research: founder backgrounds, funding history, competitive landscape, regulatory context, product maturity, and red flags.

### 3. Radar monitors the market

Daily scans for funding rounds, exits, and trend signals. Weekly monitoring of regulatory changes (configurable per vertical) and investor activity (configurable watch list). Weekly synthesis uses Claude Opus to distil signals into thesis implications.

### 4. Ops maintains the tracker

Weekly audit of all tracked companies. Web searches for recent news. Hiring signal checks via Adzuna. Flags staleness (>30 days), recommends promotions for breakout performers, recommends kills for companies that have pivoted, shut down, or gone stale. Cross-references with radar signals.

### 5. Read your briefs

All output goes to `outputs/daily/` and `outputs/weekly/` as markdown files. Committed to the repo by GitHub Actions, so the full history is version-controlled and auditable.

---

## Quick Start

```bash
git clone https://github.com/lachlan-sear/thesis-agent.git
cd thesis-agent
pip install -r requirements.txt
cp .env.example .env   # Add your ANTHROPIC_API_KEY
```

### Run agents

```bash
python main.py run --all --max-queries 24   # Run all three agents
python main.py run --scout              # Scout only
python main.py run --radar              # Radar only
python main.py run --radar --weekly     # Include weekly synthesis
python main.py run --ops                # Ops only
python main.py run --scout --dry-run    # No API calls — tests structure and free sources
python main.py run --scout --max-queries 20  # Control search depth
```

> **Note:** `--max-queries` controls how many web search queries to run. 24 gives ~3 queries per primary vertical. Reduce to 8 for a quick scan, increase to 40 for deep coverage.

### Utilities

```bash
python main.py thesis     # Display current thesis config
python main.py health     # Show tracker health
python main.py history    # Show run history
```

---

## Model Routing

Not every task needs the most powerful model. thesis-agent routes intelligently:

| Task | Model | Why |
|------|-------|-----|
| Bulk evaluation | Sonnet | High volume, structured JSON output |
| Company enrichment | Sonnet | Research tasks, web search |
| Brief generation | Opus | Synthesis quality matters |
| Trend synthesis | Opus | Nuanced, judgement-adjacent analysis |
| Staleness audit | Sonnet | Simple binary checks |
| Promotion analysis | Opus | Requires calibrated recommendations |

---

## Project Structure

```
thesis-agent/
├── config/
│   ├── thesis.yaml              # Investment thesis (the brain)
│   └── tracker_state.json       # Currently tracked companies
├── agents/
│   ├── scout/                   # Agent 1: Deal Sourcing
│   │   ├── scout.py             # Pipeline orchestrator (12 sources)
│   │   ├── evaluator.py         # Claude-powered scoring (5 frameworks)
│   │   ├── enricher.py          # Deep research on high scorers
│   │   └── sources/
│   │       ├── web_search.py    # Claude web search (7 query categories)
│   │       ├── hn.py            # Hacker News
│   │       ├── companies_house.py # UK incorporations
│   │       ├── github_trending.py # Developer traction
│   │       ├── adzuna_hiring.py # Hiring velocity signals
│   │       ├── rss.py           # RSS feeds
│   │       ├── producthunt.py   # Product launches
│   │       ├── reddit.py        # Practitioner signals
│   │       ├── patents.py       # IP defensibility
│   │       ├── wikipedia.py     # Mindshare trends
│   │       ├── podcasts.py      # VC podcast monitoring
│   │       └── twitter.py       # X/Twitter signals
│   ├── radar/                   # Agent 2: Market Intelligence
│   │   └── radar.py             # Funding, exits, trends, regulatory, synthesis
│   └── ops/                     # Agent 3: Tracker Management
│       └── ops.py               # Staleness, promotions, kills, cross-refs
├── shared/
│   ├── claude_client.py         # API wrapper with model routing
│   ├── config_loader.py         # Thesis config parser (7 query categories)
│   ├── models.py                # Pydantic data models
│   └── db.py                    # SQLite persistence
├── tests/
│   └── test_core.py             # Core logic tests
├── examples/                    # Sample outputs (Sports Tech thesis)
├── outputs/
│   ├── daily/                   # Scout briefs + radar signals
│   └── weekly/                  # Ops reviews + radar synthesis
├── main.py                      # CLI entry point
├── .github/workflows/
│   ├── daily_run.yml            # Daily: scout + radar at 7am UTC
│   └── weekly_review.yml        # Weekly: ops + synthesis on Mondays
└── requirements.txt
```

---

## Customisation

### Use your own thesis

Edit `config/thesis.yaml`. Change the verticals, signals, rubric, regulatory monitoring queries, and investor watch list. The entire system re-orients automatically.

### Add sources

Each source implements `fetch() → list[RawCandidate]`. Drop a new file in `agents/scout/sources/`, import it in the scout orchestrator, and it's live.

### Adjust scoring

The evaluation rubric weights in `shared/models.py` provide universal defaults. To override per-fund, add an `evaluation_weights` section to your `thesis.yaml` — the evaluator will use those weights instead. Add an `evaluation_weights` section to your `thesis.yaml` to override the default weights for your fund's priorities.

---

## Philosophy

> "The next $1T company will be a software company masquerading as a services firm." — Julien Bek, Sequoia

Most deal sourcing tools sell the tool. Harmonic gives you a dashboard. Dealroom gives you a database. You still need an analyst to evaluate every company against your thesis.

thesis-agent sells the work. It sources, evaluates, enriches, monitors, and maintains — then delivers a brief. The human decides what to do with it. That's the only part that requires judgement.

---

## Built With

- **Python 3.12** — standard library for most data sources (no heavy dependencies)
- **Claude API** — Sonnet for bulk work, Opus for synthesis
- **SQLite** — Deduplication and signal history
- **GitHub Actions** — Scheduling and output versioning
- **Pydantic** — Typed data models throughout
- **PyYAML** — Thesis configuration

---

## License

MIT
