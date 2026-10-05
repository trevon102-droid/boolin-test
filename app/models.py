from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class DataStatus(str, Enum):
    OK = "ok"
    PARTIAL = "partial"
    ERROR = "error"
    SKIPPED = "skipped"


class EvidenceKind(str, Enum):
    CONFIRMED = "confirmed"
    PROJECTED = "projected"
    DERIVED = "derived"


class ResearchDecision(str, Enum):
    LEAN = "lean"
    PASS = "pass"
    WATCH = "watch"
    INSUFFICIENT = "insufficient"


class MarketSnapshot(BaseModel):
    timestamp: datetime
    bookmaker: str
    market: str
    side: str | None = None
    line: float | None = None
    price: int | None = None
    implied_probability: float | None = None


class ModelView(BaseModel):
    win_probability: float | None = Field(default=None, ge=0, le=1)
    projected_spread: float | None = None
    projected_total: float | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    sample_size: int | None = Field(default=None, ge=0)


class AvailabilityItem(BaseModel):
    name: str
    status: str
    evidence_kind: EvidenceKind = EvidenceKind.PROJECTED
    source: str
    updated_at: datetime
    note: str | None = None


class ResearchSource(BaseModel):
    name: str
    source_type: EvidenceKind
    fetched_at: datetime
    status: DataStatus
    age_seconds: int
    fields: list[str] = Field(default_factory=list)
    error: str | None = None


class ResearchFlag(BaseModel):
    code: str
    severity: str
    title: str
    explanation: str
    source_fields: list[str] = Field(default_factory=list)


class ChangeEvent(BaseModel):
    timestamp: datetime
    category: str
    field: str
    old_value: Any
    new_value: Any
    source: str
    causal_link_confirmed: bool = False
    explanation: str | None = None


class Scenario(BaseModel):
    name: str
    assumption: str
    projected_probability: float | None = Field(default=None, ge=0, le=1)
    projected_spread: float | None = None
    projected_total: float | None = None
    delta_probability: float | None = None
    delta_spread: float | None = None
    delta_total: float | None = None


class ResearchGame(BaseModel):
    game_id: str
    league: str
    start_time: datetime
    home_team: str
    away_team: str
    venue: str | None = None
    market: list[MarketSnapshot] = Field(default_factory=list)
    model: ModelView = Field(default_factory=ModelView)
    availability: list[AvailabilityItem] = Field(default_factory=list)
    sources: list[ResearchSource] = Field(default_factory=list)
    flags: list[ResearchFlag] = Field(default_factory=list)
    scenarios: list[Scenario] = Field(default_factory=list)
    summary_supporting: list[str] = Field(default_factory=list)
    summary_contradicting: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    decision: ResearchDecision = ResearchDecision.INSUFFICIENT


class IndependentOpinion(BaseModel):
    engine: str = "independent-v1"
    methodology: str = "Market-consensus baseline with explicit uncertainty penalties; does not reuse Boolin Analyst engine outputs."
    market_probability: float | None = Field(default=None, ge=0, le=1)
    market_spread: float | None = None
    market_total: float | None = None
    movement_signal: str = "unknown"
    availability_signal: str = "unknown"
    data_quality: str = "unknown"
    confidence: float = Field(ge=0, le=1)
    decision: ResearchDecision = ResearchDecision.INSUFFICIENT
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AuditFinding(BaseModel):
    code: str
    severity: str
    title: str
    explanation: str
    evidence: list[str] = Field(default_factory=list)


class DualAudit(BaseModel):
    game_id: str
    verdict: str
    agreement_score: float = Field(ge=0, le=1)
    analyst: dict[str, Any]
    independent: IndependentOpinion
    findings: list[AuditFinding] = Field(default_factory=list)
    questions_for_review: list[str] = Field(default_factory=list)


class AnalystNoteCreate(BaseModel):
    thesis: str
    supporting_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    decision: ResearchDecision = ResearchDecision.WATCH
    entry_trigger: str | None = None


class AnalystNote(AnalystNoteCreate):
    id: int
    game_id: str
    created_at: datetime
    updated_at: datetime


class PostgameReviewCreate(BaseModel):
    thesis_grade: str
    market_read_grade: str | None = None
    injury_grade: str | None = None
    matchup_grade: str | None = None
    weather_grade: str | None = None
    what_was_right: list[str] = Field(default_factory=list)
    what_was_wrong: list[str] = Field(default_factory=list)
    closing_line: str | None = None
    actual_result: str
    lessons: list[str] = Field(default_factory=list)


class PostgameReview(PostgameReviewCreate):
    id: int
    game_id: str
    created_at: datetime


class ResearchBoardItem(BaseModel):
    game_id: str
    matchup: str
    research_score: int = Field(ge=0, le=100)
    reasons: list[str]
    flags: list[str]
    start_time: datetime
