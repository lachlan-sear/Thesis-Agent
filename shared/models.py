"""
thesis-radar data models.
Pydantic models for companies, signals, evaluations, and reports.
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class Stage(str, Enum):
    PRE_SEED = "pre-seed"
    SEED = "seed"
    SERIES_A = "series-a"
    SERIES_B = "series-b"
    SERIES_C = "series-c"
    GROWTH = "growth"
    UNKNOWN = "unknown"


class Action(str, Enum):
    TRACK = "track"
    WATCH = "watch"
    SKIP = "skip"


class SignalType(str, Enum):
    FUNDING = "funding"
    EXIT = "exit"
    REGULATORY = "regulatory"
    MODEL_UPDATE = "model-update"
    COMPETITIVE = "competitive"
    PRODUCT_LAUNCH = "product-launch"
    HIRING = "hiring"
    SHUTDOWN = "shutdown"


class Urgency(str, Enum):
    NORMAL = "normal"
    ALERT = "alert"
    CRITICAL = "critical"


class TrackerStatus(str, Enum):
    ACTIVE = "active"
    STALE = "stale"
    KILLED = "killed"
    BENCHMARK = "benchmark"


# --- Scout Models ---

class RawCandidate(BaseModel):
    """A company found by a source, before evaluation."""
    name: str
    url: Optional[str] = None
    description: str
    source: str  # "hn", "producthunt", "web_search", "rss", etc.
    source_url: Optional[str] = None
    discovered_at: datetime = Field(default_factory=datetime.utcnow)
    raw_context: Optional[str] = None  # Additional context from source


class Evaluation(BaseModel):
    """Claude's evaluation of a company against the thesis."""
    company_name: str
    customer_durability: Optional[int] = Field(None, ge=1, le=10)
    unit_economics: Optional[int] = Field(None, ge=1, le=10)
    regulation_moat: Optional[int] = Field(None, ge=1, le=10)
    growth_inflection: Optional[int] = Field(None, ge=1, le=10)
    founder_quality: Optional[int] = Field(None, ge=1, le=10)
    thesis_fit: Optional[int] = Field(None, ge=1, le=10)
    autopilot_potential: Optional[int] = Field(None, ge=1, le=10)
    funding_stage_score: Optional[int] = Field(None, ge=1, le=10)
    tam_score: Optional[int] = Field(None, ge=1, le=10)
    revenue_model_score: Optional[int] = Field(None, ge=1, le=10)
    gtm_score: Optional[int] = Field(None, ge=1, le=10)
    geo_scalability: Optional[int] = Field(None, ge=1, le=10)
    exit_potential: Optional[int] = Field(None, ge=1, le=10)
    composite_score: float = 0.0
    one_liner: str = ""
    bull_case: str = ""
    bear_case: str = ""
    action: Action = Action.SKIP
    reasoning: str = ""
    funding_detail: str = ""       # e.g. "$20M Series A led by Singular, firstminute followed on"
    revenue_model_type: str = ""   # e.g. "subscription", "transactional", "marketplace", "usage-based", "hybrid"
    gtm_strategy: str = ""         # e.g. "PLG", "direct sales", "partnerships", "viral"
    exit_comparables: str = ""     # e.g. "Veeva ($40B), Provet Cloud (acquired by IDEXX)"

    def compute_composite(self, custom_weights: dict = None) -> float:
        """Weighted average of available scores. Accepts custom weights from thesis config."""
        default_weights = {
            "thesis_fit": 0.12,
            "customer_durability": 0.12,
            "regulation_moat": 0.10,
            "unit_economics": 0.10,
            "growth_inflection": 0.10,
            "founder_quality": 0.10,
            "autopilot_potential": 0.08,
            "funding_stage_score": 0.07,
            "tam_score": 0.07,
            "revenue_model_score": 0.06,
            "gtm_score": 0.06,
            "geo_scalability": 0.05,
            "exit_potential": 0.05,
        }
        weights = custom_weights if custom_weights else default_weights
        total_weight = 0.0
        total_score = 0.0
        for field, weight in weights.items():
            val = getattr(self, field, None)
            if val is not None:
                total_score += val * weight
                total_weight += weight
        self.composite_score = round(total_score / total_weight, 1) if total_weight > 0 else 0.0
        return self.composite_score


class EnrichedCompany(BaseModel):
    """A fully researched company ready for the brief."""
    name: str
    url: Optional[str] = None
    description: str
    vertical: str
    stage: Stage = Stage.UNKNOWN
    geography: Optional[str] = None
    founded: Optional[str] = None
    funding_total: Optional[str] = None
    last_round: Optional[str] = None
    investors: list[str] = []
    founders: list[str] = []
    founder_backgrounds: Optional[str] = None
    competitive_landscape: Optional[str] = None
    regulatory_context: Optional[str] = None
    product_maturity: Optional[str] = None
    connection_paths: Optional[str] = None
    tam_estimate: Optional[str] = None          # e.g. "$12B global veterinary software market"
    revenue_model: Optional[str] = None         # e.g. "SaaS subscription per clinic"
    gtm_strategy: Optional[str] = None          # e.g. "Partnership-led via Vetsure (1,200 clinics)"
    distribution_advantage: Optional[str] = None # e.g. "Exclusive Vetsure partnership"
    exit_comparables: Optional[str] = None      # e.g. "IDEXX acquired Provet Cloud; Veeva IPO at $40B"
    investor_quality: Optional[str] = None      # e.g. "Singular (led), firstminute (follow-on)"
    evaluation: Evaluation
    source: str
    discovered_at: datetime = Field(default_factory=datetime.utcnow)


# --- Radar Models ---

class Signal(BaseModel):
    """A market signal detected by the radar agent."""
    type: SignalType
    source: str
    source_url: Optional[str] = None
    company: Optional[str] = None
    vertical: str
    summary: str
    thesis_implication: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    urgency: Urgency = Urgency.NORMAL
    affects_tracked: list[str] = []  # Names of tracked companies affected


# --- Ops Models ---

class TrackerEntry(BaseModel):
    """A company currently in the tracker."""
    name: str
    url: Optional[str] = None
    vertical: str
    stage: Stage = Stage.UNKNOWN
    status: TrackerStatus = TrackerStatus.ACTIVE
    composite_score: Optional[float] = None
    last_updated: datetime
    added_at: datetime
    notes: Optional[str] = None
    benchmark: bool = False
    stale_days: int = 0


class OpsRecommendation(BaseModel):
    """A recommendation from the ops agent."""
    company: str
    action: str  # "promote", "kill", "update", "refresh"
    reasoning: str
    evidence: Optional[str] = None
    urgency: Urgency = Urgency.NORMAL


# --- Report Models ---

class ScoutBrief(BaseModel):
    """Daily scout output."""
    date: str
    raw_candidates: int
    passed_dedup: int
    high_scoring: int
    recommended_track: list[EnrichedCompany] = []
    watch_list: list[EnrichedCompany] = []
    skipped: list[dict] = []  # {"name": ..., "reason": ...}


class RadarDigest(BaseModel):
    """Weekly radar output."""
    week_of: str
    signals: list[Signal] = []
    thesis_implications: str = ""
    tracked_alerts: list[dict] = []


class OpsReview(BaseModel):
    """Weekly ops output."""
    date: str
    total_tracked: int
    flagged_stale: int
    funding_updates: int
    shutdowns_detected: int
    promotions: list[OpsRecommendation] = []
    kills: list[OpsRecommendation] = []
    updates: list[OpsRecommendation] = []
    dossier_crossrefs: list[dict] = []
