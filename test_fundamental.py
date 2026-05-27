"""
Unified fundamental scorer — test suite.
Tests: fetch accuracy, cache round-trip, screener integration, bulk fetch.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")

from core.fundamental_scorer import (
    get_quality, get_cached_quality, get_quality_bulk,
    cache_stats, FUND_DIR
)

DIVIDER = "=" * 58

def test_single(ticker="INFY.NS"):
    print(f"\n{DIVIDER}")
    print(f"  Full fetch: {ticker}")
    print(DIVIDER)
    q = get_quality(ticker, force=True)
    score = q["qual_score"]
    tier  = q["qual_tier"]
    color = q["qual_tier_color"]
    print(f"  Score: {score}/10   Tier: {color} {tier}\n")
    print(f"  {'Signal':<35} Result")
    print(f"  {'-'*55}")
    for name, desc in q["qual_breakdown"].items():
        print(f"  {name:<35} {desc}")
    return q


def test_cache_roundtrip(ticker="INFY.NS"):
    print(f"\n  Cache round-trip: {ticker}")
    fresh = get_quality(ticker, force=True)
    cached = get_cached_quality(ticker)
    assert fresh["qual_score"] == cached["qual_score"], "Cache mismatch!"
    print(f"  Fresh: {fresh['qual_score']}/10   Cached: {cached['qual_score']}/10   Match: OK")


def test_unknown_ticker():
    print("\n  UNKNOWN ticker (no cache):")
    q = get_cached_quality("FAKEXYZ.NS")
    assert q["qual_tier"] == "UNKNOWN", "Should return UNKNOWN tier"
    assert q["qual_score"] is None, "Score should be None"
    print("  Returns UNKNOWN tier with None score: OK")


def test_bulk():
    tickers = ["HDFCBANK.NS", "WIPRO.NS", "COALINDIA.NS", "TITAN.NS"]
    print(f"\n{DIVIDER}")
    print("  Bulk fetch (4 tickers)")
    print(DIVIDER)
    results = get_quality_bulk(tickers, delay=0.3, force=True, verbose=True)
    print(f"\n  {'Ticker':<18} {'Score':>6}  Tier")
    print(f"  {'-'*40}")
    for t, q in results.items():
        score = q["qual_score"]
        tier  = q["qual_tier"]
        color = q["qual_tier_color"]
        print(f"  {t:<18} {str(score):>4}/10  {color} {tier}")
    return results


def test_screener_integration():
    print(f"\n  Screener integration (get_cached_quality keys):")
    q = get_cached_quality("INFY.NS")
    required = [
        "qual_score", "qual_tier", "qual_tier_color", "qual_breakdown",
        "qual_signals", "qual_roe", "qual_rev_growth", "qual_current",
        "qual_roa_cur", "qual_roa_prv", "qual_gm_cur", "qual_gm_prv",
        "qual_debt_cur", "qual_debt_prv", "qual_cfo_gt_ni",
        "qual_pe", "qual_pb", "qual_sector", "qual_fetched_at",
    ]
    missing = [k for k in required if k not in q]
    if missing:
        print(f"  MISSING KEYS: {missing}")
    else:
        print(f"  All {len(required)} required keys present: OK")
    return not missing


def test_cache_stats():
    s = cache_stats()
    print(f"\n  Cache stats: {s}")


if __name__ == "__main__":
    print(f"\n  FUND_DIR: {FUND_DIR}")
    print(f"\n  Running unified fundamental scorer tests...")

    q = test_single("INFY.NS")
    test_cache_roundtrip("INFY.NS")
    test_unknown_ticker()
    results = test_bulk()
    ok = test_screener_integration()
    test_cache_stats()

    # Sanity checks
    print(f"\n{DIVIDER}")
    print("  Sanity checks:")
    infy_score = q["qual_score"]
    titan_score = results.get("TITAN.NS", {}).get("qual_score", 0) or 0
    print(f"  INFY.NS score {infy_score}/10 >= 5 : {'PASS' if infy_score >= 5 else 'FAIL'}")
    print(f"  TITAN.NS score {titan_score}/10 >= 5 : {'PASS' if titan_score >= 5 else 'FAIL'}")
    print(f"  All screener keys present:    {'PASS' if ok else 'FAIL'}")
    print(f"\n  Done.")
