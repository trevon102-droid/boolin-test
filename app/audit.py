from __future__ import annotations

from .independent import build_independent_opinion
from .models import AuditFinding, DataStatus, DualAudit, ResearchDecision, ResearchGame


def _decision_strength(decision: ResearchDecision) -> int:
    return {
        ResearchDecision.INSUFFICIENT: 0,
        ResearchDecision.PASS: 1,
        ResearchDecision.WATCH: 2,
        ResearchDecision.LEAN: 3,
    }[decision]


def build_dual_audit(game: ResearchGame) -> DualAudit:
    independent = build_independent_opinion(game)
    findings: list[AuditFinding] = []
    questions: list[str] = []

    analyst_probability = game.model.win_probability
    probability_gap = (
        abs(analyst_probability - independent.market_probability)
        if analyst_probability is not None and independent.market_probability is not None
        else None
    )

    if probability_gap is not None and probability_gap >= 0.05:
        findings.append(
            AuditFinding(
                code="MODEL_MARKET_CONFLICT",
                severity="high",
                title="Analyst model materially disagrees with market baseline",
                explanation=f"The analyst model differs from the independent market-consensus baseline by {probability_gap:.1%}.",
                evidence=[
                    f"Analyst model probability: {analyst_probability:.1%}.",
                    f"Independent market probability: {independent.market_probability:.1%}.",
                ],
            )
        )
        questions.append("What independent team-level evidence justifies the model divergence from the market?")

    if game.model.sample_size is not None and game.model.sample_size < 5 and game.model.confidence is not None and game.model.confidence >= 0.65:
        findings.append(
            AuditFinding(
                code="OVERCONFIDENT_SMALL_SAMPLE",
                severity="high",
                title="Confidence may be too high for the sample size",
                explanation="The analyst model reports high confidence despite a very small sample.",
                evidence=[
                    f"Sample size: {game.model.sample_size}.",
                    f"Reported confidence: {game.model.confidence:.1%}.",
                ],
            )
        )
        questions.append("Why should this confidence level survive the small-sample penalty?")

    unresolved = {a.status.lower() for a in game.availability} & {"questionable", "probable", "projected"}
    if unresolved and game.decision == ResearchDecision.LEAN:
        findings.append(
            AuditFinding(
                code="UNRESOLVED_AVAILABILITY",
                severity="medium",
                title="Lean decision despite unresolved availability",
                explanation="A lean conclusion is being presented while player/starter availability remains unresolved.",
                evidence=[f"Unresolved statuses: {sorted(unresolved)}."],
            )
        )
        questions.append("What happens to the conclusion when the unresolved player is inactive?")

    unhealthy = [
        source.name
        for source in game.sources
        if source.status in {DataStatus.PARTIAL, DataStatus.ERROR}
    ]
    if unhealthy and game.decision == ResearchDecision.LEAN:
        findings.append(
            AuditFinding(
                code="PARTIAL_DATA_LEAN",
                severity="high",
                title="Lean decision relies on unhealthy source data",
                explanation="At least one source feeding the research card is partial or failed.",
                evidence=[f"Affected sources: {', '.join(unhealthy)}."],
            )
        )
        questions.append("Which parts of the conclusion remain valid if the affected source is removed?")

    if game.unknowns and game.decision == ResearchDecision.LEAN:
        findings.append(
            AuditFinding(
                code="UNKNOWN_VARIABLES_IGNORED",
                severity="medium",
                title="Lean decision contains unresolved unknowns",
                explanation="The research card still lists unknown variables while presenting a lean decision.",
                evidence=[f"Unknowns: {', '.join(game.unknowns[:5])}."],
            )
        )
        questions.append("Which unknown would most change the thesis?")

    moneyline_book_count = len([
        m for m in game.market
        if m.market == "moneyline" and m.implied_probability is not None
    ])

    findings.append(
        AuditFinding(
            subject="independent",
            code="INDEPENDENT_MARKET_ONLY",
            severity="medium",
            title="Independent layer is a market-first control model",
            explanation="The second layer intentionally does not reuse the primary model or hidden team-level assumptions. Its strongest use is auditing confidence and market divergence, not producing a full team-performance forecast.",
            evidence=[
                "Independent probability is derived from the latest available moneyline observations.",
                "No primary model fields are used to build the independent probability.",
            ],
        )
    )

    if moneyline_book_count < 2:
        findings.append(
            AuditFinding(
                subject="independent",
                code="INDEPENDENT_LOW_MARKET_COVERAGE",
                severity="medium",
                title="Independent layer has thin market coverage",
                explanation="The control model has fewer than two usable bookmaker moneyline observations.",
                evidence=[f"Usable moneyline observations: {moneyline_book_count}."],
            )
        )

    if independent.warnings and independent.confidence < 0.60:
        findings.append(
            AuditFinding(
                code="INDEPENDENT_LOW_CONFIDENCE",
                severity="medium",
                title="Independent layer is deliberately low-confidence",
                explanation="The independent layer has insufficient evidence quality for a strong conclusion.",
                evidence=independent.warnings[:5],
            )
        )

    analyst_strength = _decision_strength(game.decision)
    independent_strength = _decision_strength(independent.decision)
    if analyst_strength == independent_strength:
        agreement = 0.90
    elif abs(analyst_strength - independent_strength) == 1:
        agreement = 0.65
    else:
        agreement = 0.35

    if probability_gap is not None:
        agreement -= min(0.25, probability_gap * 1.5)

    agreement = max(0.0, min(1.0, round(agreement, 3)))

    if any(f.severity == "high" for f in findings):
        verdict = "REVIEW_REQUIRED"
    elif agreement >= 0.80:
        verdict = "ALIGNED"
    elif agreement >= 0.55:
        verdict = "PARTIAL_AGREEMENT"
    else:
        verdict = "CONFLICT"

    if not findings:
        questions.append("What evidence would falsify both layers?")

    return DualAudit(
        game_id=game.game_id,
        verdict=verdict,
        agreement_score=agreement,
        analyst={
            "decision": game.decision.value,
            "win_probability": game.model.win_probability,
            "projected_spread": game.model.projected_spread,
            "projected_total": game.model.projected_total,
            "confidence": game.model.confidence,
            "sample_size": game.model.sample_size,
            "unknowns": game.unknowns,
        },
        independent=independent,
        findings=findings,
        questions_for_review=questions[:8],
    )
