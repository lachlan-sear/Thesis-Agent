# thesis-agent

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
│                      thesis.yaml                         │
│            (configurable investment thesis)               │
└────────────────────────┬────────────────────────────────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
    ┌───────────┐  ┌───────────┐  ┌───────────┐
    │   SCOUT   │  │   RADAR   │  │    OPS    │
    │  (daily)  │  │  (daily)  │  │ (weekly)  │
    │           │  │           │  │           │
    │ Sources   │  │ Funding   │  │ Staleness │
    │ Dedup     │  │ Exits     │  │ Promotion │
    │ Evaluate  │  │ Trends    │  │ Kill      │
    │ Enrich    │  │ Regulate  │  │ X-ref     │
    └─────┬─────┘  └─────┬─────┘  └─────┬─────┘
          │              │              │
          ▼              ▼              ▼
    Scout Brief    Radar Digest    Ops Review
    (markdown)     (markdown)      (markdown)
```

| Agent | Schedule | What it does |
|-------|----------|--------------|
| **Scout** | Daily | Sources new companies from web search, Hacker News, RSS. Evaluates each against the thesis (scored 1-10 across 7 dimensions). Enriches top hits with deep research. Outputs a brief with recommendations. |
| **Radar** | Daily + Weekly | Monitors funding rounds, exits, shutdowns, regulatory shifts, and competitive moves across thesis verticals. Weekly synthesis distils signals into thesis implications. |
| **Ops** | Weekly | Audits the tracker for staleness. Checks tracked companies for news. Suggests promotions (to benchmark tier) and kills. Cross-references with radar signals. |

The agents reinforce each other. Scout finds a company → Radar catches a regulatory change in the same vertical → Ops cross-references both and flags the update.

---

## How It Works

### 1. Define your thesis

Everything flows from `config/thesis.yaml`. It defines:

- Target verticals (primary, secondary, emerging)
- Positive and negative signals
- Stage and geography focus
- Evaluation rubric with weighted dimensions
- Portfolio exemplars for calibration

The thesis is fully configurable. A healthcare investor, a fintech fund, a climate tech scout — each swaps in their own config and the entire system re-orients.

### 2. Scout sources companies

The scout agent searches across multiple sources in parallel:

- **Claude web search** — targeted queries generated from thesis verticals
- **Hacker News** — Show HN posts and top stories, keyword-filtered
- **RSS feeds** — configurable feed list (Sifted, TechCrunch, etc.)
- **Companies House API** — UK incorporations by SIC code (free, public)

Each candidate is deduplicated against the SQLite history, then evaluated by Claude against the thesis rubric. Companies scoring 7+ get a deep enrichment pass: founder backgrounds, funding history, competitive landscape, regulatory context.

### 3. Radar monitors the market

Daily scans for funding rounds, exits, and trend signals across thesis verticals. Weekly synthesis uses Claude Opus to distil a week's signals into thesis implications — what's heating up, what's cooling down, what should change sourcing priorities.

### 4. Ops maintains the tracker

Weekly audit of all tracked companies. Web searches for recent news on each entry. Flags staleness (>30 days since update), suggests promotions for breakout performers, suggests kills for companies that have pivoted away, shut down, or gone stale.

### 5. Read your briefs

All output goes to `outputs/daily/` and `outputs/weekly/` as markdown files. Committed to the repo by GitHub Actions, so the full history of what was sourced, evaluated, and recommended is version-controlled and auditable.

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
# Run all three agents
python main.py run --all

# Run individually
python main.py run --scout
python main.py run --radar
python main.py run --radar --weekly    # Include weekly synthesis
python main.py run --ops

# Dry run (no API calls — tests structure and HN source)
python main.py run --scout --dry-run

# Control search depth
python main.py run --scout --max-queries 20
```

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

## Customisation

### Use your own thesis

Edit `config/thesis.yaml`. Change the verticals, signals, rubric, and exemplars. The entire system re-orients automatically.

A climate tech investor swaps in different verticals (energy storage, carbon capture, grid), different positive signals (IP portfolio, regulatory incentive alignment), and different exemplars. Same architecture, different intelligence.

### Add sources

Each source implements a simple pattern: `fetch() → list[RawCandidate]`. Add a new file to `agents/scout/sources/`, import it in the scout orchestrator, and it's live.

### Adjust scoring

The evaluation rubric weights in `shared/models.py` control how the composite score is calculated. Increase the weight on `regulation_moat` if moat matters more than growth inflection for your thesis.

---

## Sequoia Framework Integration

The evaluation rubric includes an `autopilot_potential` dimension, inspired by Sequoia's "Services: The New Software" thesis.

This scores whether a company is selling the work (autopilot) or selling the tool (copilot). Companies that capture service and labour budgets rather than software budgets get higher marks — they have larger TAM, stronger lock-in, and benefit directly from model improvements rather than being threatened by them.

---

## Project Structure

```
thesis-agent/
├── config/
│   ├── thesis.yaml              # Investment thesis (the brain)
│   └── tracker_state.json       # Current tracked companies
├── agents/
│   ├── scout/                   # Agent 1: Deal Sourcing
│   │   ├── scout.py             # Pipeline orchestrator
│   │   ├── evaluator.py         # Claude-powered thesis scoring
│   │   ├── enricher.py          # Deep research on high scorers
│   │   └── sources/
│   │       ├── web_search.py    # Claude web search discovery
│   │       └── hn.py            # Hacker News scanner
│   ├── radar/                   # Agent 2: Market Intelligence
│   │   └── radar.py             # Funding, exits, trends, synthesis
│   └── ops/                     # Agent 3: Tracker Management
│       └── ops.py               # Staleness, promotions, kills
├── shared/
│   ├── claude_client.py         # API wrapper with model routing
│   ├── config_loader.py         # Thesis config parser
│   ├── models.py                # Pydantic data models
│   └── db.py                    # SQLite persistence
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

## Cost Estimate

Running daily with 10 search queries and a 12-company tracker:

| Agent | Frequency | Estimated API cost |
|-------|-----------|-------------------|
| Scout (10 queries + eval) | Daily | ~$0.50-1.50/day |
| Radar (3 monitors) | Daily | ~$0.30-0.80/day |
| Ops (12 company checks) | Weekly | ~$0.50-1.00/week |
| **Total** | | **~$25-70/month** |

---

## Built With

- **Python 3.12**
- **Claude API** — Sonnet for bulk work, Opus for synthesis
- **SQLite** — Deduplication and signal history
- **GitHub Actions** — Scheduling and output versioning
- **Pydantic** — Typed data models throughout
- **PyYAML** — Thesis configuration

---

## Philosophy

> "The next $1T company will be a software company masquerading as a services firm." — Julien Bek, Sequoia

Most deal sourcing tools sell the tool. Harmonic gives you a dashboard. Dealroom gives you a database. You still need an analyst to evaluate every company against your thesis.

thesis-agent sells the work. It sources, evaluates, enriches, monitors, and maintains — then delivers a brief. The human decides what to do with it. That's the only part that requires judgement.

---

## License

MIT
