from __future__ import annotations

import pandas as pd

import data.multi_source_router as multi_source_router


class _FakeRouter:
    failures: set[str] = set()
    init_failures: set[str] = set()

    def __init__(self, source: str) -> None:
        if source in self.init_failures:
            raise ImportError(f"{source} import failed")
        self.source = source
        self.loader = object()
        self.closed = False
        self.last_validation = None

    def get_option_chain(self, symbol: str) -> pd.DataFrame:
        if self.source in self.failures:
            raise ValueError(f"{self.source} unavailable")
        frame = pd.DataFrame(
            [
                {
                    "symbol": symbol,
                    "source": self.source,
                    "strikePrice": 24000,
                    "OPTION_TYP": "CE",
                    "lastPrice": 100.0,
                }
            ]
        )
        self.last_validation = {
            "is_valid": True,
            "analytics_usable": True,
            "execution_suggestion_usable": self.source == "ZERODHA",
            "provider_health": {
                "summary_status": "GOOD",
                "source": self.source,
                "market_data_readiness_score": 91.0,
            },
            "warnings": [],
            "issues": [],
        }
        return frame

    def get_expiry_candidates(self) -> list:
        return [f"{self.source}-expiry"]

    def close(self) -> None:
        self.closed = True


def test_multi_source_router_returns_primary_and_records_secondary(monkeypatch):
    _FakeRouter.failures = set()
    _FakeRouter.init_failures = set()
    monkeypatch.setattr(multi_source_router, "DataSourceRouter", _FakeRouter)

    router = multi_source_router.MultiSourceDataRouter(
        ["ICICI", "ZERODHA"],
        primary_source="ICICI",
        max_workers=2,
    )

    frame = router.get_option_chain("NIFTY")

    assert frame.iloc[0]["source"] == "ICICI"
    assert set(router.last_provider_frames) == {"ICICI", "ZERODHA"}
    assert router.last_collection["enabled"] is True
    assert router.last_collection["primary_source"] == "ICICI"
    assert router.last_collection["primary_decision_source"] == "ICICI"
    assert router.last_collection["secondary_research_sources"] == ["ZERODHA"]
    assert router.last_collection["successful_sources"] == ["ICICI", "ZERODHA"]
    assert router.last_collection["failed_sources"] == []
    provider_roles = {
        record["source"]: (record["decision_role"], record["research_only"])
        for record in router.last_collection["provider_records"]
    }
    assert provider_roles == {
        "ICICI": ("PRIMARY_DECISION_SOURCE", False),
        "ZERODHA": ("SECONDARY_RESEARCH_ONLY", True),
    }
    assert router.get_expiry_candidates() == ["ICICI-expiry"]

    router.close()
    assert all(fake.closed for fake in router.routers.values())


def test_multi_source_router_single_source_keeps_compatibility(monkeypatch):
    _FakeRouter.failures = set()
    _FakeRouter.init_failures = set()
    monkeypatch.setattr(multi_source_router, "DataSourceRouter", _FakeRouter)

    router = multi_source_router.MultiSourceDataRouter(["ZERODHA"], primary_source="ZERODHA")
    frame = router.get_option_chain("NIFTY")

    assert frame.iloc[0]["source"] == "ZERODHA"
    assert router.source == "ZERODHA"
    assert router.last_collection["mode"] == "SINGLE_SOURCE"
    assert router.last_collection["enabled"] is False


def test_multi_source_router_primary_failure_is_explicit_but_secondary_is_recorded(monkeypatch):
    _FakeRouter.failures = {"ICICI"}
    _FakeRouter.init_failures = set()
    monkeypatch.setattr(multi_source_router, "DataSourceRouter", _FakeRouter)

    router = multi_source_router.MultiSourceDataRouter(
        ["ICICI", "ZERODHA"],
        primary_source="ICICI",
        max_workers=2,
    )

    try:
        router.get_option_chain("NIFTY")
    except ValueError as exc:
        assert "Primary data source ICICI failed" in str(exc)
    else:
        raise AssertionError("expected primary failure")

    assert router.last_collection["primary_ok"] is False
    assert router.last_collection["successful_sources"] == ["ZERODHA"]
    assert router.last_collection["failed_sources"] == ["ICICI"]
    assert set(router.last_provider_frames) == {"ZERODHA"}


def test_multi_source_router_secondary_initialization_failure_does_not_block_primary(monkeypatch):
    _FakeRouter.failures = set()
    _FakeRouter.init_failures = {"ICICI"}
    monkeypatch.setattr(multi_source_router, "DataSourceRouter", _FakeRouter)

    router = multi_source_router.MultiSourceDataRouter(
        ["ZERODHA", "ICICI"],
        primary_source="ZERODHA",
        max_workers=2,
    )

    frame = router.get_option_chain("NIFTY")

    assert frame.iloc[0]["source"] == "ZERODHA"
    assert router.last_collection["primary_ok"] is True
    assert router.last_collection["successful_sources"] == ["ZERODHA"]
    assert router.last_collection["failed_sources"] == ["ICICI"]
    assert "ImportError" in router.last_collection["provider_records"][1]["error"]
