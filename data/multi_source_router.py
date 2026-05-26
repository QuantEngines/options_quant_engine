"""
Module: multi_source_router.py

Purpose:
    Fetch option-chain snapshots from multiple providers in parallel while
    preserving the single-provider engine contract.

Role in the System:
    Part of the data layer. It lets the live engine keep one primary decision
    source and simultaneously collect secondary provider evidence for research,
    provider-quality comparison, and future reconciliation work.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import pandas as pd

from config.market_data_policy import IST_TIMEZONE
from config.settings import DATA_SOURCE_OPTIONS
from data.data_source_router import DataSourceRouter


def normalize_source_list(sources: list[str] | tuple[str, ...] | str | None, *, primary_source: str | None = None) -> list[str]:
    """Return provider names normalized, deduplicated, and primary-first."""
    if isinstance(sources, str):
        raw_values = [item.strip() for item in sources.split(",")]
    else:
        raw_values = list(sources or [])

    allowed = set(DATA_SOURCE_OPTIONS)
    normalized: list[str] = []
    for raw in raw_values:
        source = str(raw or "").upper().strip()
        if not source:
            continue
        if source not in allowed:
            raise ValueError(f"Unsupported data source {source!r}. Allowed values: {DATA_SOURCE_OPTIONS}")
        if source not in normalized:
            normalized.append(source)

    primary = str(primary_source or "").upper().strip()
    if primary:
        if primary not in allowed:
            raise ValueError(f"Unsupported primary data source {primary!r}. Allowed values: {DATA_SOURCE_OPTIONS}")
        normalized = [source for source in normalized if source != primary]
        normalized.insert(0, primary)

    if not normalized:
        raise ValueError("At least one data source is required.")
    return normalized


def _now_ist() -> pd.Timestamp:
    return pd.Timestamp.now(tz=IST_TIMEZONE)


def _provider_health_summary(validation: dict[str, Any] | None) -> dict[str, Any]:
    validation = validation if isinstance(validation, dict) else {}
    health = validation.get("provider_health") if isinstance(validation.get("provider_health"), dict) else {}
    tradable = validation.get("tradable_data") if isinstance(validation.get("tradable_data"), dict) else {}
    return {
        "summary_status": health.get("summary_status"),
        "row_health": health.get("row_health"),
        "pricing_health": health.get("pricing_health"),
        "quote_health": health.get("quote_health"),
        "iv_health": health.get("iv_health"),
        "readiness_score": health.get("market_data_readiness_score"),
        "readiness_tier": health.get("market_data_readiness_tier"),
        "trade_blocking_status": health.get("trade_blocking_status"),
        "trade_blocking_reasons": list(health.get("trade_blocking_reasons") or []),
        "analytics_usable": validation.get("analytics_usable"),
        "execution_suggestion_usable": validation.get("execution_suggestion_usable"),
        "tradable_data_status": tradable.get("status"),
        "tradable_data_score": tradable.get("score"),
        "warnings": list(validation.get("warnings") or []),
        "issues": list(validation.get("issues") or []),
    }


class MultiSourceDataRouter:
    """Parallel option-chain collector with a primary-source compatibility API."""

    def __init__(
        self,
        sources: list[str] | tuple[str, ...] | str,
        *,
        primary_source: str | None = None,
        max_workers: int | None = None,
    ) -> None:
        self.sources = normalize_source_list(sources, primary_source=primary_source)
        self.primary_source = self.sources[0]
        self.source = self.primary_source
        self.max_workers = max(1, int(max_workers or min(len(self.sources), 4)))
        self.routers = {source: DataSourceRouter(source) for source in self.sources}
        self.last_validation = None
        self.last_collection: dict[str, Any] | None = None
        self.last_provider_frames: dict[str, pd.DataFrame] = {}

    @property
    def loader(self):
        """Expose the primary loader for existing spot-source helpers."""
        primary_router = self.routers.get(self.primary_source)
        return getattr(primary_router, "loader", None)

    def _fetch_one(self, source: str, symbol: str) -> dict[str, Any]:
        router = self.routers[source]
        started = _now_ist()
        start_perf = time.perf_counter()
        try:
            frame = router.get_option_chain(symbol)
            validation = router.last_validation if isinstance(router.last_validation, dict) else {}
            finished = _now_ist()
            return {
                "source": source,
                "ok": True,
                "frame": frame,
                "validation": validation,
                "row_count": int(len(frame)) if frame is not None else 0,
                "started_at": started.isoformat(),
                "finished_at": finished.isoformat(),
                "elapsed_ms": round((time.perf_counter() - start_perf) * 1000.0, 3),
                "error": None,
            }
        except Exception as exc:
            finished = _now_ist()
            return {
                "source": source,
                "ok": False,
                "frame": None,
                "validation": None,
                "row_count": 0,
                "started_at": started.isoformat(),
                "finished_at": finished.isoformat(),
                "elapsed_ms": round((time.perf_counter() - start_perf) * 1000.0, 3),
                "error": f"{type(exc).__name__}: {exc}",
            }

    def get_option_chain(self, symbol: str):
        """Fetch all configured providers and return the primary provider frame."""
        results: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {
                pool.submit(self._fetch_one, source, symbol): source
                for source in self.sources
            }
            for future in as_completed(futures):
                record = future.result()
                results[record["source"]] = record

        provider_records = []
        provider_frames: dict[str, pd.DataFrame] = {}
        for source in self.sources:
            record = results.get(source) or {
                "source": source,
                "ok": False,
                "row_count": 0,
                "validation": None,
                "error": "missing_fetch_result",
            }
            frame = record.pop("frame", None)
            if record.get("ok") and isinstance(frame, pd.DataFrame):
                provider_frames[source] = frame
            validation = record.get("validation")
            serializable = dict(record)
            serializable["validation"] = _provider_health_summary(validation)
            provider_records.append(serializable)

        successful_sources = [record["source"] for record in provider_records if record.get("ok")]
        failed_sources = [record["source"] for record in provider_records if not record.get("ok")]
        primary_record = results.get(self.primary_source)
        primary_ok = bool(primary_record and primary_record.get("ok"))

        self.last_provider_frames = provider_frames
        self.last_validation = (
            primary_record.get("validation")
            if primary_ok and isinstance(primary_record.get("validation"), dict)
            else None
        )
        self.last_collection = {
            "enabled": len(self.sources) > 1,
            "mode": "MULTI_SOURCE_PARALLEL" if len(self.sources) > 1 else "SINGLE_SOURCE",
            "primary_source": self.primary_source,
            "requested_sources": list(self.sources),
            "successful_sources": successful_sources,
            "failed_sources": failed_sources,
            "provider_records": provider_records,
            "primary_ok": primary_ok,
            "primary_error": None if primary_ok else (primary_record or {}).get("error"),
        }

        if not primary_ok:
            error = self.last_collection.get("primary_error") or "primary provider fetch failed"
            raise ValueError(f"Primary data source {self.primary_source} failed during multi-source fetch: {error}")

        return provider_frames[self.primary_source]

    def get_expiry_candidates(self) -> list:
        primary_router = self.routers.get(self.primary_source)
        if primary_router is None or not hasattr(primary_router, "get_expiry_candidates"):
            return []
        return primary_router.get_expiry_candidates()

    def close(self) -> None:
        for router in self.routers.values():
            try:
                router.close()
            except Exception:
                pass
