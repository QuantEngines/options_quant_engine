from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from analytics.greeks_engine import _bs_price_for_iv, _parse_expiry_years
from research.signal_evaluation.provider_quality_comparison import (
    build_provider_quality_comparison,
    write_provider_quality_comparison_report,
)


def _write_chain(path: Path, *, source: str, two_sided_quotes: bool) -> None:
    rows = []
    for idx, strike in enumerate(range(23800, 24200, 50)):
        for option_type in ("CE", "PE"):
            bid = 95.0 + idx
            ask = bid + 1.0
            rows.append(
                {
                    "strikePrice": float(strike),
                    "OPTION_TYP": option_type,
                    "lastPrice": 100.0 + idx,
                    "bidPrice": bid,
                    "askPrice": ask if two_sided_quotes else 0.0,
                    "openInterest": 1_000_000 + idx * 100_000 + (50_000 if option_type == "PE" else 0),
                    "changeinOI": 10_000 + idx,
                    "totalTradedVolume": 25_000 + idx,
                    "impliedVolatility": 0.22 + idx * 0.001,
                    "source": source,
                    "expiryDate": "2026-05-28",
                    "quote_timestamp": "2026-05-26T09:30:00+05:30",
                }
            )
    pd.DataFrame(rows).to_csv(path, index=False)


def _write_zero_iv_priced_chain(path: Path, *, source: str) -> None:
    spot = 24000.0
    expiry = "2026-06-30"
    valuation_time = "2026-05-26T09:30:00+05:30"
    tte = _parse_expiry_years(expiry, valuation_time=valuation_time)
    rows = []
    for strike in range(23500, 24550, 50):
        for option_type in ("CE", "PE"):
            price = _bs_price_for_iv(spot, strike, tte, 0.16, option_type)
            bid = max(price - 0.05, price * 0.99, 0.01)
            ask = max(price + 0.05, bid + 0.01)
            rows.append(
                {
                    "strikePrice": float(strike),
                    "OPTION_TYP": option_type,
                    "lastPrice": price,
                    "bidPrice": bid,
                    "askPrice": ask,
                    "openInterest": 1_000_000,
                    "changeinOI": 10_000,
                    "totalTradedVolume": 25_000,
                    "impliedVolatility": 0.0,
                    "IV": 0.0,
                    "source": source,
                    "EXPIRY_DT": expiry,
                    "quote_timestamp": valuation_time,
                }
            )
    pd.DataFrame(rows).to_csv(path, index=False)


def test_provider_quality_comparison_pairs_nearby_snapshots(tmp_path: Path) -> None:
    option_dir = tmp_path / "option_chain_snapshots"
    spot_dir = tmp_path / "spot_snapshots"
    option_dir.mkdir()
    spot_dir.mkdir()

    _write_chain(
        option_dir / "NIFTY_ICICI_option_chain_snapshot_2026-05-26T09-30-00+05-30.csv",
        source="ICICI",
        two_sided_quotes=False,
    )
    _write_chain(
        option_dir / "NIFTY_ZERODHA_option_chain_snapshot_2026-05-26T09-30-45+05-30.csv",
        source="ZERODHA",
        two_sided_quotes=True,
    )
    (spot_dir / "NIFTY_spot_snapshot_2026-05-26T09-30-00+05-30.json").write_text(
        json.dumps({"spot": 24000.0, "timestamp": "2026-05-26T09:30:00+05:30"}),
        encoding="utf-8",
    )

    report = build_provider_quality_comparison(
        symbol="NIFTY",
        sources=("ICICI", "ZERODHA"),
        session_date="2026-05-26",
        option_snapshot_dir=option_dir,
        spot_snapshot_dir=spot_dir,
        max_pair_seconds=90,
    )

    assert len(report["snapshot_profiles"]) == 2
    assert len(report["paired_comparisons"]) == 1
    assert report["comparison_scope"] == "OFFLINE_RESEARCH_ONLY"
    assert "secondary sources are research-only" in report["live_decision_policy"]
    pair = report["paired_comparisons"][0]
    assert pair["pair_delta_seconds"] == 45.0
    assert pair["right_after_left_seconds"] == 45.0
    assert pair["research_only"] is True
    assert pair["causal_replay_eligible"] is False
    assert pair["pairing_note"] == "offline_near_sync_research_pair_right_after_left"
    assert pair["right_source"] == "ZERODHA"
    assert pair["right_quoted_ratio"] > pair["left_quoted_ratio"]
    assert pair["execution_preferred_source"] in {"ZERODHA", "TIE"}


def test_provider_quality_comparison_writes_latest_outputs(tmp_path: Path) -> None:
    report = {
        "generated_at": "2026-05-26T09:30:00+05:30",
        "symbol": "NIFTY",
        "session_date": "2026-05-26",
        "sources": ["ICICI", "ZERODHA"],
        "snapshot_profiles": [],
        "paired_comparisons": [],
        "unpaired_snapshots": [],
        "source_summary": [],
        "pair_preference_counts": {"analytics": {}, "execution": {}},
    }

    paths = write_provider_quality_comparison_report(report, output_dir=tmp_path)

    assert Path(paths["latest_markdown"]).exists()
    assert Path(paths["latest_json"]).exists()
    assert Path(paths["latest_profiles_csv"]).exists()
    assert Path(paths["latest_pairs_csv"]).exists()


def test_provider_quality_comparison_derives_missing_provider_iv(tmp_path: Path) -> None:
    option_dir = tmp_path / "option_chain_snapshots"
    spot_dir = tmp_path / "spot_snapshots"
    option_dir.mkdir()
    spot_dir.mkdir()

    _write_zero_iv_priced_chain(
        option_dir / "NIFTY_ZERODHA_option_chain_snapshot_2026-05-26T09-30-00+05-30.csv",
        source="ZERODHA",
    )
    (spot_dir / "NIFTY_spot_snapshot_2026-05-26T09-30-00+05-30.json").write_text(
        json.dumps({"spot": 24000.0, "timestamp": "2026-05-26T09:30:00+05:30"}),
        encoding="utf-8",
    )

    report = build_provider_quality_comparison(
        symbol="NIFTY",
        sources=("ZERODHA", "ICICI"),
        session_date="2026-05-26",
        option_snapshot_dir=option_dir,
        spot_snapshot_dir=spot_dir,
        max_pair_seconds=90,
    )

    profile = report["snapshot_profiles"][0]
    assert profile["source"] == "ZERODHA"
    assert profile["iv_validation_source"] == "MODEL_DERIVED_FROM_OPTION_PRICE"
    assert profile["raw_positive_iv_rows"] == 0
    assert profile["validation_positive_iv_rows"] > 0
    assert profile["core_iv_health"] in {"GOOD", "CAUTION"}
    assert profile["atm_iv_health"] in {"GOOD", "CAUTION"}
    assert "core_iv_weak" not in profile["trade_blocking_reasons"]
