"""Market integrity: side matching, no-vig pairing, per-series movement, alternate lines, audit findings.

Cases 1-4 are the defects reproduced on the pre-fix code (order-dependent moneyline comparison, raw-vig
averaging of one arbitrary side per book, cross-book/cross-side movement, alternate lines merged into one move).
"""
from datetime import datetime, timedelta, timezone

import pytest

from app import matching
from app.audit import build_dual_audit
from app.engine import compare_market_model, market_summary
from app.independent import build_independent_opinion, movement_records
from app.marketmath import devig, implied
from app.models import MarketSnapshot, ModelView, ResearchGame

T0 = datetime(2026, 10, 5, 13, 30, tzinfo=timezone.utc)
T1 = datetime(2026, 10, 5, 15, 30, tzinfo=timezone.utc)


def snap(t, book, market, side, line, price, **kw):
    imp = round(implied(price), 4) if market == "moneyline" else None
    return MarketSnapshot(timestamp=t, bookmaker=book, market=market, side=side, line=line, price=price,
                          implied_probability=imp, **kw)


def mkgame(market, perspective="BUF", win=0.455, spread=1.7):
    return ResearchGame(
        game_id="T", league="NFL", start_time=datetime(2026, 10, 11, 20, 20, tzinfo=timezone.utc),
        home_team="KC", away_team="BUF", market=market,
        model=ModelView(perspective=perspective, win_probability=win, projected_spread=spread, projected_total=44.8),
    )


def two_sided_moneyline():
    return [snap(T1, "fanduel", "moneyline", "BUF", None, 145), snap(T1, "fanduel", "moneyline", "KC", None, -170),
            snap(T1, "pinnacle", "moneyline", "BUF", None, 139), snap(T1, "pinnacle", "moneyline", "KC", None, -155)]


def expected_buf_fair():
    fd = devig([implied(145), implied(-170)])[0]
    pn = devig([implied(139), implied(-155)])[0]
    return (fd + pn) / 2


# ---------- 1. moneyline comparison is side-matched and order-independent ----------

def test_compare_uses_perspective_side_and_no_vig():
    r = compare_market_model(mkgame(two_sided_moneyline()))
    assert r["market_probability_basis"] == "no_vig_consensus" and r["market_books"] == ["fanduel", "pinnacle"]
    assert r["market_win_probability"] == pytest.approx(expected_buf_fair(), abs=1e-4)
    assert r["probability_delta"] == pytest.approx(0.455 - expected_buf_fair(), abs=1e-4)


def test_compare_is_independent_of_input_order():
    ml = two_sided_moneyline()
    a = compare_market_model(mkgame(ml))
    b = compare_market_model(mkgame(list(reversed(ml))))
    assert a == b  # before the fix this flipped between 0.408 ('mild') and 0.608 ('significant')


def test_other_perspective_gets_the_complement():
    buf = compare_market_model(mkgame(two_sided_moneyline(), perspective="BUF"))["market_win_probability"]
    kc = compare_market_model(mkgame(two_sided_moneyline(), perspective="KC", win=0.55))["market_win_probability"]
    home = compare_market_model(mkgame(two_sided_moneyline(), perspective="home", win=0.55))["market_win_probability"]
    assert buf + kc == pytest.approx(1, abs=1e-3) and kc == home


def test_missing_or_invalid_perspective_skips_comparison_with_warning():
    for persp, code in ((None, "MODEL_PERSPECTIVE_UNSPECIFIED"), ("NYJ", "MODEL_PERSPECTIVE_INVALID")):
        r = compare_market_model(mkgame(two_sided_moneyline(), perspective=persp))
        assert "probability_delta" not in r and "spread_delta" not in r
        assert any(w.startswith(code) for w in r["warnings"])


# ---------- 2. independent consensus: paired, no-vig, order-independent ----------

def test_independent_probability_is_no_vig_for_a_named_team():
    op = build_independent_opinion(mkgame(two_sided_moneyline()))
    assert op.market_probability_side == "BUF" and op.market_probability_basis == "no_vig_consensus"
    assert op.market_probability == pytest.approx(expected_buf_fair(), abs=1e-4)
    assert op.market_books == ["fanduel", "pinnacle"]
    assert build_independent_opinion(mkgame(list(reversed(two_sided_moneyline())))).market_probability == op.market_probability


def test_independent_defaults_to_home_team_when_no_perspective():
    op = build_independent_opinion(mkgame(two_sided_moneyline(), perspective=None))
    assert op.market_probability_side == "KC" and op.market_probability == pytest.approx(1 - expected_buf_fair(), abs=1e-3)


def test_one_sided_quotes_fall_back_to_raw_and_say_so():
    ml = [snap(T1, "fanduel", "moneyline", "BUF", None, 135)]
    r = compare_market_model(mkgame(ml))
    assert r["market_probability_basis"] == "raw_implied_vig_included"
    assert any(w.startswith("MARKET_PROBABILITY_INCLUDES_VIG") for w in r["warnings"])
    op = build_independent_opinion(mkgame(ml))
    assert op.market_probability_basis == "raw_implied_vig_included" and any("margin" in w for w in op.warnings)


def test_unsynchronized_sides_are_excluded_not_mixed():
    ml = [snap(T1, "fanduel", "moneyline", "BUF", None, 145),
          snap(T1 + timedelta(hours=2), "fanduel", "moneyline", "KC", None, -170),   # 2h apart
          snap(T1, "pinnacle", "moneyline", "BUF", None, 139), snap(T1, "pinnacle", "moneyline", "KC", None, -155)]
    fm = matching.fair_moneyline(mkgame(ml), "BUF")
    assert fm["books"] == ["pinnacle"] and "min apart" in fm["excluded"]["fanduel"]
    assert fm["probability"] == pytest.approx(devig([implied(139), implied(-155)])[0], abs=1e-4)


def test_ambiguous_same_timestamp_quotes_are_excluded():
    ml = two_sided_moneyline() + [snap(T1, "fanduel", "moneyline", "BUF", None, 160)]  # second BUF price, same instant
    fm = matching.fair_moneyline(mkgame(ml), "BUF")
    assert "fanduel" not in fm["books"] and "ambiguous" in fm["excluded"]["fanduel"]


def test_alternate_or_other_period_quotes_never_feed_the_main_probability():
    ml = two_sided_moneyline() + [snap(T1, "fanduel", "moneyline", "BUF", None, 600, period="first_half"),
                                  snap(T1, "fanduel", "moneyline", "KC", None, -900, period="first_half")]
    assert matching.fair_moneyline(mkgame(ml), "BUF")["probability"] == pytest.approx(expected_buf_fair(), abs=1e-4)


# ---------- 3. movement is per bookmaker / side / line ----------

def test_movement_is_calculated_per_series_not_across_sides_or_books():
    sp = [snap(T0, "pinnacle", "spread", "BUF", 3.5, -110), snap(T0, "pinnacle", "spread", "KC", -3.5, -110),
          snap(T1, "pinnacle", "spread", "BUF", 3.0, -108), snap(T1, "pinnacle", "spread", "KC", -3.0, -112),
          snap(T0, "fanduel", "spread", "BUF", 2.5, -110), snap(T1, "fanduel", "spread", "BUF", 2.5, -110)]
    recs = {(r["bookmaker"], r["side"]): r for r in movement_records(mkgame(sp), ("spread",))}
    assert recs[("pinnacle", "BUF")]["status"] == "LINE_ONLY_MOVE" and recs[("pinnacle", "BUF")]["line_delta"] == -0.5
    assert recs[("pinnacle", "BUF")]["toward_selection"] is True      # BUF's handicap shrank: market likes BUF more
    assert recs[("pinnacle", "KC")]["line_delta"] == 0.5 and recs[("pinnacle", "KC")]["toward_selection"] is False
    assert recs[("fanduel", "BUF")]["status"] == "STABLE"            # FanDuel is not dragged by Pinnacle's move
    assert recs[("fanduel", "BUF")]["opening_line"] == recs[("fanduel", "BUF")]["current_line"] == 2.5


def test_movement_summary_is_order_independent():
    sp = [snap(T0, "pinnacle", "spread", "BUF", 3.5, -110), snap(T1, "pinnacle", "spread", "BUF", 3.0, -110),
          snap(T0, "pinnacle", "spread", "KC", -3.5, -110), snap(T1, "pinnacle", "spread", "KC", -3.0, -110)]
    a, b = build_independent_opinion(mkgame(sp)), build_independent_opinion(mkgame(list(reversed(sp))))
    assert a.movement_signal == b.movement_signal == "line_moved"


def test_movement_statuses_and_missing_data():
    one = movement_records(mkgame([snap(T0, "pinnacle", "spread", "BUF", 3.5, -110)]), ("spread",))
    assert one[0]["status"] == "INSUFFICIENT_HISTORY" and one[0]["line_delta"] is None
    nothing = movement_records(mkgame([MarketSnapshot(timestamp=T0, bookmaker="x", market="spread", side="BUF"),
                                       MarketSnapshot(timestamp=T1, bookmaker="x", market="spread", side="BUF")]), ("spread",))
    assert nothing[0]["status"] == "UNKNOWN"                           # missing data is UNKNOWN, never invented movement
    price_only = movement_records(mkgame([snap(T0, "pinnacle", "spread", "BUF", 3.5, -110),
                                          snap(T1, "pinnacle", "spread", "BUF", 3.5, -125)]), ("spread",))
    assert price_only[0]["status"] == "PRICE_ONLY_MOVE" and price_only[0]["line_delta"] == 0 and price_only[0]["toward_selection"] is True


def test_price_delta_not_reported_across_even_money():
    r = movement_records(mkgame([snap(T0, "fanduel", "moneyline", "BUF", None, 105),
                                 snap(T1, "fanduel", "moneyline", "BUF", None, -105)]), ("moneyline",))[0]
    assert r["side"] == "BUF" and r["bookmaker"] == "fanduel"  # original casing preserved
    assert r["price_delta"] is None and r["implied_delta"] == pytest.approx(implied(-105) - implied(105), abs=1e-4)
    assert r["status"] == "PRICE_ONLY_MOVE" and r["toward_selection"] is True


def test_total_movement_direction_depends_on_over_or_under():
    t = [snap(T0, "pinnacle", "total", "over", 47.5, -110), snap(T1, "pinnacle", "total", "over", 46.0, -110),
         snap(T0, "pinnacle", "total", "under", 47.5, -110), snap(T1, "pinnacle", "total", "under", 46.0, -110)]
    recs = {r["side"]: r for r in movement_records(mkgame(t), ("total",))}
    assert recs["over"]["toward_selection"] is False and recs["under"]["toward_selection"] is True


# ---------- 4. alternate lines ----------

def test_labelled_alternate_lines_are_separate_series():
    sp = [snap(T0, "pinnacle", "spread", "BUF", 3.5, -110), snap(T1, "pinnacle", "spread", "BUF", 3.5, -110),
          snap(T0, "pinnacle", "spread", "BUF", 6.5, -170, line_id="alt+6.5"), snap(T1, "pinnacle", "spread", "BUF", 6.5, -170, line_id="alt+6.5")]
    rows = market_summary(mkgame(sp))
    assert len(rows) == 2 and {r["line_id"] for r in rows} == {None, "alt+6.5"}
    assert all(r["line_move"] == 0 for r in rows)                      # before the fix: one row, fabricated +3.0 move
    assert matching.market_spread_for(mkgame(sp), "BUF").line == 3.5   # main line, never the alt


def test_unlabelled_concurrent_lines_are_flagged_ambiguous():
    sp = [snap(T0, "pinnacle", "spread", "BUF", 3.5, -110), snap(T0, "pinnacle", "spread", "BUF", 6.5, -170)]
    g = mkgame(sp)
    assert len(matching.ambiguous_snapshots(g)) == 1
    assert market_summary(g)[0]["ambiguous"] is True
    assert any("AMBIGUOUS" in w for w in compare_market_model(g)["warnings"])
    assert "MARKET_AMBIGUOUS_SNAPSHOTS" in {f.code for f in build_dual_audit(g).findings}


# ---------- spread / total matching ----------

def test_spread_comparison_uses_the_perspective_teams_line_only():
    sp = [snap(T1, "pinnacle", "spread", "BUF", 3.0, -108), snap(T1, "pinnacle", "spread", "KC", -3.0, -112)]
    buf = compare_market_model(mkgame(sp, perspective="BUF", spread=1.7))
    kc = compare_market_model(mkgame(list(reversed(sp)), perspective="KC", spread=-1.7))
    assert buf["market_spread"] == 3.0 and buf["spread_delta"] == pytest.approx(-1.3)
    assert kc["market_spread"] == -3.0 and kc["spread_delta"] == pytest.approx(1.3)


def test_total_comparison_is_side_independent():
    t = [snap(T1, "pinnacle", "total", "over", 46.0, -110), snap(T1, "pinnacle", "total", "under", 46.0, -110)]
    assert compare_market_model(mkgame(t))["total_delta"] == pytest.approx(44.8 - 46.0)


# ---------- audit ----------

def test_audit_flags_uncomparable_model_and_does_not_invent_a_gap():
    audit = build_dual_audit(mkgame(two_sided_moneyline(), perspective=None))
    codes = {f.code for f in audit.findings}
    assert "MARKET_COMPARISON_INVALID" in codes and "MODEL_MARKET_CONFLICT" not in codes and audit.verdict == "REVIEW_REQUIRED"


def test_audit_compares_when_sides_match_and_counts_books_not_snapshots():
    audit = build_dual_audit(mkgame(two_sided_moneyline(), win=0.60))
    codes = {f.code for f in audit.findings}
    assert "MODEL_MARKET_CONFLICT" in codes and "MARKET_COMPARISON_INVALID" not in codes
    same_book_twice = [snap(T0, "fanduel", "moneyline", "BUF", None, 145), snap(T1, "fanduel", "moneyline", "BUF", None, 140)]
    assert "INDEPENDENT_LOW_MARKET_COVERAGE" in {f.code for f in build_dual_audit(mkgame(same_book_twice)).findings}


# ---------- odds math ----------

def test_marketmath_edge_cases():
    assert devig([implied(-110), implied(-110)]) == pytest.approx([0.5, 0.5])
    assert sum(devig([0.4, 0.35, 0.3])) == pytest.approx(1)
    for bad in ([None, 0.5], [0.5], [], None, [0.5, 1.2], [0.5, float("nan")]):
        assert devig(bad) is None
    for bad in (None, 0, 50, "x", float("inf"), True):
        assert implied(bad) is None
