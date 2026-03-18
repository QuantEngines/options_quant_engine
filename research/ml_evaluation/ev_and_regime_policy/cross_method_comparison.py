"""
Cross-Method Predictor & Policy Comparison Runner
===================================================
Unifies results from ALL evaluation pipelines into a single
comparison report: existing predictors, decision policies,
rank-gate sizing, EV-based sizing, and regime-switching policies.

Author: Pramit Dutta
Organization: Quant Engines

RESEARCH ONLY
"""
from __future__ import annotations

import json
import logging
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).resolve().parent
PRED_DIR = Path(__file__).resolve().parents[1] / "predictor_comparison"
DPC_PATH = Path(__file__).resolve().parents[1] / "decision_policy_comparison.json"
RGS_DIR = Path(__file__).resolve().parents[1] / "rank_gate_sizing"

# ── Helpers ──────────────────────────────────────────────────────────

def _rnd(v: float | None, d: int = 2) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return round(f, d) if np.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _save(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")
    logger.info("Saved → %s", path)


# ── Gatherers ────────────────────────────────────────────────────────

def _gather_predictor_methods() -> list[dict]:
    """Load results from predictor_comparison_runner (backtest set)."""
    p = PRED_DIR / "predictor_comparison_results.json"
    if not p.exists():
        return []
    d = json.loads(p.read_text(encoding="utf-8"))
    rows = []
    for r in d.get("backtest_results", []):
        rows.append({
            "category": "predictor",
            "method": r["predictor"],
            "description": r.get("description", ""),
            "n_signals": r.get("n_trade", 0),
            "retention_pct": _rnd(r.get("retention_pct")),
            "hit_rate": _rnd(r.get("trade_hit_rate"), 4),
            "avg_return_bps": _rnd(r.get("trade_avg_return_bps")),
            "cumulative_return_bps": _rnd(r.get("trade_cumulative_bps")),
            "max_drawdown_bps": _rnd(r.get("trade_max_dd_bps")),
            "volatility_bps": _rnd(r.get("trade_volatility_bps")),
            "sharpe_proxy": _rnd(r.get("trade_sharpe"), 4),
            "prob_return_corr": _rnd(r.get("prob_return_corr"), 4),
        })
    return rows


def _gather_decision_policies() -> list[dict]:
    """Load decision-policy comparison."""
    if not DPC_PATH.exists():
        return []
    d = json.loads(DPC_PATH.read_text(encoding="utf-8"))
    rows = []
    if isinstance(d, dict):
        for key, val in d.items():
            if isinstance(val, dict) and "n" in val:
                rows.append({
                    "category": "decision_policy",
                    "method": key,
                    "description": "",
                    "n_signals": val.get("n"),
                    "retention_pct": _rnd(val.get("n", 0) / 7404 * 100) if val.get("n") else None,
                    "hit_rate": _rnd(val.get("hit_rate_60m", val.get("hit_rate")), 4),
                    "avg_return_bps": _rnd(val.get("avg_return_60m_bps", val.get("avg_return_bps"))),
                    "cumulative_return_bps": None,
                    "max_drawdown_bps": None,
                    "volatility_bps": None,
                    "sharpe_proxy": None,
                })
    elif isinstance(d, list):
        for item in d:
            if isinstance(item, dict):
                rows.append({
                    "category": "decision_policy",
                    "method": item.get("policy", item.get("label", "?")),
                    "description": "",
                    "n_signals": item.get("n"),
                    "retention_pct": _rnd(item.get("n", 0) / 7404 * 100) if item.get("n") else None,
                    "hit_rate": _rnd(item.get("hit_rate_60m", item.get("hit_rate")), 4),
                    "avg_return_bps": _rnd(item.get("avg_return_60m_bps")),
                    "cumulative_return_bps": None,
                    "max_drawdown_bps": None,
                    "volatility_bps": None,
                    "sharpe_proxy": None,
                })
    return rows


def _gather_rank_gate_sizing() -> list[dict]:
    """Load rank-gate + confidence sizing."""
    p = RGS_DIR / "rank_gate_sizing_results.json"
    if not p.exists():
        return []
    d = json.loads(p.read_text(encoding="utf-8"))
    rows = []
    for r in d.get("comparison", []):
        rows.append({
            "category": "rank_gate_sizing",
            "method": r.get("label", "?"),
            "description": "",
            "n_signals": r.get("n"),
            "retention_pct": _rnd(r.get("retention_pct")),
            "hit_rate": _rnd(r.get("hit_rate"), 4),
            "avg_return_bps": _rnd(r.get("avg_return_60m_bps")),
            "cumulative_return_bps": _rnd(r.get("cumulative_return_bps")),
            "max_drawdown_bps": _rnd(r.get("max_drawdown_bps")),
            "volatility_bps": _rnd(r.get("volatility_bps")),
            "sharpe_proxy": _rnd(r.get("sharpe_proxy"), 4),
            "sized_avg_return_bps": _rnd(r.get("sized_avg_return_bps")),
            "sized_cumulative_bps": _rnd(r.get("sized_cumulative_return_bps")),
            "sized_sharpe": _rnd(r.get("sized_sharpe_proxy"), 4),
        })
    return rows


def _gather_ev_sizing() -> list[dict]:
    """Load EV-based sizing evaluation."""
    p = OUTPUT_DIR / "ev_sizing_report.json"
    if not p.exists():
        return []
    d = json.loads(p.read_text(encoding="utf-8"))
    rows = []
    for r in d.get("comparison", []):
        rows.append({
            "category": "ev_sizing",
            "method": r.get("label", "?"),
            "description": "EV-based sizing",
            "n_signals": r.get("n"),
            "retention_pct": _rnd(r.get("retention_pct")),
            "hit_rate": _rnd(r.get("hit_rate"), 4),
            "avg_return_bps": _rnd(r.get("avg_return_60m_bps")),
            "cumulative_return_bps": _rnd(r.get("cumulative_return_bps")),
            "max_drawdown_bps": _rnd(r.get("max_drawdown_bps")),
            "volatility_bps": _rnd(r.get("volatility_bps")),
            "sharpe_proxy": _rnd(r.get("sharpe_proxy"), 4),
            "sized_avg_return_bps": _rnd(r.get("sized_avg_return_bps")),
            "sized_cumulative_bps": _rnd(r.get("sized_cumulative_return_bps")),
            "sized_sharpe": _rnd(r.get("sized_sharpe_proxy"), 4),
        })
    ev_buckets = d.get("ev_bucket_breakdown", [])
    return rows, ev_buckets


def _gather_regime_switching() -> list[dict]:
    """Load regime-switching policy evaluation."""
    p = OUTPUT_DIR / "regime_switching_report.json"
    if not p.exists():
        return [], None
    d = json.loads(p.read_text(encoding="utf-8"))
    rows = []
    for r in d.get("search_results", []):
        if r.get("n", 0) == 0:
            continue
        rows.append({
            "category": "regime_switching",
            "method": r.get("label", "?"),
            "description": "Regime-switched policy",
            "n_signals": r.get("n"),
            "retention_pct": _rnd(r.get("retention_pct")),
            "hit_rate": _rnd(r.get("hit_rate"), 4),
            "avg_return_bps": _rnd(r.get("avg_return_60m_bps")),
            "cumulative_return_bps": _rnd(r.get("cumulative_return_bps")),
            "max_drawdown_bps": _rnd(r.get("max_drawdown_bps")),
            "volatility_bps": _rnd(r.get("volatility_bps")),
            "sharpe_proxy": _rnd(r.get("sharpe_proxy"), 4),
            "sized_avg_return_bps": _rnd(r.get("sized_avg_return_bps")),
            "sized_cumulative_bps": _rnd(r.get("sized_cumulative_return_bps")),
            "sized_sharpe": _rnd(r.get("sized_sharpe_proxy"), 4),
        })
    best = d.get("best_variant")
    return rows, best


# ── Charts ───────────────────────────────────────────────────────────

def _generate_comparison_charts(unified: list[dict], ev_buckets: list[dict]) -> list[str]:
    warnings.filterwarnings("ignore", category=UserWarning)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    saved: list[str] = []

    # ── Select key methods for the headline chart ────────────────────
    headline_methods = [
        ("blended",                   "predictor",       "Blended (prod)"),
        ("pure_ml",                   "predictor",       "Pure ML"),
        ("research_dual",             "predictor",       "research_dual"),
        ("decision_policy",           "predictor",       "dual_thresh (pred)"),
        ("rank_gate_30",              "rank_gate_sizing", "Rank Gate 30"),
        ("rank_gate_40",              "rank_gate_sizing", "Rank Gate 40"),
        ("rank_filtered_ev_sized",    "ev_sizing",       "EV Sized (rank 30)"),
        ("all_ev_sized",              "ev_sizing",       "EV Sized (all)"),
        ("static_rank_gate_40",       "regime_switching", "Static RG40"),
        ("default_gamma_driven",      "regime_switching", "Gamma-Driven"),
        ("defensive_gamma_vol",       "regime_switching", "Defensive G+V"),
        ("ev_favorable_regime",       "regime_switching", "EV + Regime"),
    ]

    lookup = {(r["method"], r["category"]): r for r in unified}
    selected = []
    labels = []
    for meth, cat, label in headline_methods:
        r = lookup.get((meth, cat))
        if r:
            selected.append(r)
            labels.append(label)

    if not selected:
        return saved

    # Color by category
    cat_colors = {
        "predictor": "#90CAF9",
        "decision_policy": "#FFE082",
        "rank_gate_sizing": "#A5D6A7",
        "ev_sizing": "#CE93D8",
        "regime_switching": "#FFAB91",
    }

    # ── 1. Headline comparison (2×2 subplots) ────────────────────────
    fig, axes = plt.subplots(2, 2, figsize=(18, 11))
    fig.suptitle("Cross-Method Comparison — All Predictor & Policy Methods\n(Backtest: 7,404 signals, 2,701 evaluable)",
                 fontsize=14, fontweight="bold")

    x = np.arange(len(labels))
    w = 0.65
    colors = [cat_colors.get(r["category"], "#BDBDBD") for r in selected]

    metrics = [
        ("hit_rate", "Hit Rate", 0.5),
        ("avg_return_bps", "Avg Return 60m (bps)", 0),
        ("cumulative_return_bps", "Cumulative Return (bps)", 0),
        ("sharpe_proxy", "Sharpe Proxy", 0),
    ]

    for idx, (metric, title, hline) in enumerate(metrics):
        ax = axes[idx // 2][idx % 2]
        vals = []
        for r in selected:
            v = r.get(metric)
            vals.append(float(v) if v is not None else 0.0)
        bars = ax.bar(x, vals, w, color=colors, edgecolor="white", linewidth=0.5)
        ax.set_title(title, fontsize=11, fontweight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
        if hline is not None:
            ax.axhline(hline, color="grey", ls="--", lw=0.8, alpha=0.5)
        for i, (v, bar) in enumerate(zip(vals, bars)):
            if v != 0:
                fmt = f"{v:.2f}" if abs(v) < 100 else f"{v:.0f}"
                va = "bottom" if v >= 0 else "top"
                ax.text(i, v, fmt, ha="center", va=va, fontsize=7, fontweight="bold")

    # Legend
    from matplotlib.patches import Patch
    legend_items = [Patch(facecolor=c, label=cat.replace("_", " ").title())
                    for cat, c in cat_colors.items()]
    axes[0][1].legend(handles=legend_items, loc="upper right", fontsize=8, framealpha=0.9)

    plt.tight_layout(rect=[0, 0, 1, 0.93])
    p = OUTPUT_DIR / "cross_method_comparison.png"
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    saved.append(str(p))

    # ── 2. Sized returns comparison ──────────────────────────────────
    sized_methods = [r for r in unified if r.get("sized_avg_return_bps") is not None and r.get("sized_sharpe") is not None]
    if sized_methods:
        fig2, ax2 = plt.subplots(figsize=(12, 6))
        fig2.suptitle("Sized Returns — Methods with Position Sizing", fontsize=12, fontweight="bold")
        slabels = [r["method"] for r in sized_methods]
        sx = np.arange(len(slabels))

        unsized = [float(r.get("avg_return_bps") or 0) for r in sized_methods]
        sized = [float(r.get("sized_avg_return_bps") or 0) for r in sized_methods]

        bw = 0.35
        ax2.bar(sx - bw/2, unsized, bw, label="Unsized Avg Return", color="#90CAF9", edgecolor="white")
        ax2.bar(sx + bw/2, sized, bw, label="Sized Avg Return", color="#CE93D8", edgecolor="white")
        ax2.set_xticks(sx)
        ax2.set_xticklabels(slabels, rotation=45, ha="right", fontsize=8)
        ax2.set_ylabel("Avg Return (bps)")
        ax2.axhline(0, color="grey", ls="--", lw=0.8, alpha=0.5)
        ax2.legend()

        # Add sharpe annotations
        for i, r in enumerate(sized_methods):
            sh_unsized = r.get("sharpe_proxy", "")
            sh_sized = r.get("sized_sharpe", "")
            ax2.text(i - bw/2, unsized[i], f"S={sh_unsized}", ha="center", va="bottom", fontsize=6)
            ax2.text(i + bw/2, sized[i], f"S={sh_sized}", ha="center", va="bottom", fontsize=6)

        plt.tight_layout()
        p2 = OUTPUT_DIR / "cross_method_sized_returns.png"
        fig2.savefig(p2, dpi=150, bbox_inches="tight")
        plt.close(fig2)
        saved.append(str(p2))

    # ── 3. Efficiency frontier (hit_rate vs sharpe) ──────────────────
    frontier_methods = [r for r in unified if r.get("sharpe_proxy") is not None and r.get("hit_rate") is not None]
    if frontier_methods:
        fig3, ax3 = plt.subplots(figsize=(10, 7))
        ax3.set_title("Efficiency Frontier — Hit Rate vs Sharpe Proxy", fontsize=12, fontweight="bold")

        for r in frontier_methods:
            c = cat_colors.get(r["category"], "#BDBDBD")
            s = max(30, min(200, (r.get("n_signals") or 100) / 30))
            ax3.scatter(float(r["hit_rate"]), float(r["sharpe_proxy"]),
                       s=s, c=c, edgecolors="black", linewidths=0.5, alpha=0.8, zorder=5)
            ax3.annotate(r["method"], (float(r["hit_rate"]), float(r["sharpe_proxy"])),
                        fontsize=6, ha="left", va="bottom", xytext=(4, 4), textcoords="offset points")

        ax3.axhline(0, color="grey", ls="--", lw=0.5, alpha=0.5)
        ax3.axvline(0.5, color="grey", ls="--", lw=0.5, alpha=0.5)
        ax3.set_xlabel("Hit Rate")
        ax3.set_ylabel("Sharpe Proxy")
        ax3.legend(handles=[Patch(facecolor=c, label=cat.replace("_", " ").title())
                            for cat, c in cat_colors.items()], fontsize=8, loc="lower right")
        plt.tight_layout()
        p3 = OUTPUT_DIR / "cross_method_efficiency_frontier.png"
        fig3.savefig(p3, dpi=150, bbox_inches="tight")
        plt.close(fig3)
        saved.append(str(p3))

    # ── 4. EV bucket performance ─────────────────────────────────────
    if ev_buckets:
        fig4, ax4 = plt.subplots(figsize=(10, 5))
        ax4.set_title("EV Bucket Performance Breakdown", fontsize=12, fontweight="bold")
        bucket_labels = [b.get("ev_bucket", "?") for b in ev_buckets]
        bx = np.arange(len(bucket_labels))
        bhr = [float(b.get("hit_rate") or 0) for b in ev_buckets]
        bret = [float(b.get("avg_return_bps") or 0) for b in ev_buckets]

        bw = 0.35
        ax4_r = ax4.twinx()
        ax4.bar(bx - bw/2, bhr, bw, label="Hit Rate", color="#A5D6A7", edgecolor="white")
        ax4_r.bar(bx + bw/2, bret, bw, label="Avg Return (bps)", color="#CE93D8", edgecolor="white")
        ax4.set_xticks(bx)
        ax4.set_xticklabels(bucket_labels, fontsize=9)
        ax4.set_ylabel("Hit Rate")
        ax4_r.set_ylabel("Avg Return (bps)")
        ax4.axhline(0.5, color="grey", ls="--", lw=0.5, alpha=0.5)

        for i, b in enumerate(ev_buckets):
            ax4.text(i - bw/2, bhr[i], f"n={b.get('n','?')}", ha="center", va="bottom", fontsize=7)

        lines1, labels1 = ax4.get_legend_handles_labels()
        lines2, labels2 = ax4_r.get_legend_handles_labels()
        ax4.legend(lines1 + lines2, labels1 + labels2, loc="upper left")

        plt.tight_layout()
        p4 = OUTPUT_DIR / "cross_method_ev_buckets.png"
        fig4.savefig(p4, dpi=150, bbox_inches="tight")
        plt.close(fig4)
        saved.append(str(p4))

    return saved


# ── Markdown report ──────────────────────────────────────────────────

def _generate_markdown(
    unified: list[dict],
    ev_buckets: list[dict],
    best_regime: dict | None,
    charts: list[str],
) -> str:
    lines = [
        "# Cross-Method Predictor & Policy Comparison",
        "",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "**Author:** Pramit Dutta  ",
        "**Organization:** Quant Engines  ",
        "",
        "**Dataset:** Backtest signals — 7,404 total signals, 2,701 with evaluable outcomes  ",
        "**Date range:** 2016 – 2025 (10 years simulated)  ",
        "",
        "---",
        "",
        "## Summary Table",
        "",
        "| Category | Method | N | Retain% | Hit Rate | Avg Ret (bps) | Cum Ret (bps) | Max DD (bps) | Sharpe |",
        "|----------|--------|---|---------|----------|---------------|---------------|--------------|--------|",
    ]

    for cat in ["predictor", "decision_policy", "rank_gate_sizing", "ev_sizing", "regime_switching"]:
        entries = [r for r in unified if r["category"] == cat]
        for r in entries:
            m = r["method"]
            n = r.get("n_signals", "")
            ret = r.get("retention_pct", "")
            hr = r.get("hit_rate", "")
            ar = r.get("avg_return_bps", "")
            cr = r.get("cumulative_return_bps", "")
            dd = r.get("max_drawdown_bps", "")
            sh = r.get("sharpe_proxy", "")
            cat_label = cat.replace("_", " ").title()
            lines.append(f"| {cat_label} | {m} | {n} | {ret} | {hr} | {ar} | {cr} | {dd} | {sh} |")

    # Key findings
    lines += ["", "---", "", "## Key Findings", ""]

    # Best by sharpe
    scored = [r for r in unified if r.get("sharpe_proxy") is not None]
    if scored:
        best_sharpe = max(scored, key=lambda r: r["sharpe_proxy"])
        lines.append(f"**Best Sharpe Proxy:** `{best_sharpe['method']}` ({best_sharpe['category']}) — "
                     f"Sharpe = **{best_sharpe['sharpe_proxy']}**, "
                     f"Hit Rate = {best_sharpe.get('hit_rate', '?')}, "
                     f"Avg Return = {best_sharpe.get('avg_return_bps', '?')} bps")
        lines.append("")

    # Best by hit rate
    if scored:
        best_hr = max(scored, key=lambda r: r.get("hit_rate") or 0)
        lines.append(f"**Best Hit Rate:** `{best_hr['method']}` ({best_hr['category']}) — "
                     f"Hit Rate = **{best_hr.get('hit_rate', '?')}**, "
                     f"Sharpe = {best_hr.get('sharpe_proxy', '?')}")
        lines.append("")

    # Best cumulative
    cum_scored = [r for r in unified if r.get("cumulative_return_bps") is not None]
    if cum_scored:
        best_cum = max(cum_scored, key=lambda r: r["cumulative_return_bps"])
        lines.append(f"**Best Cumulative Return:** `{best_cum['method']}` ({best_cum['category']}) — "
                     f"Cumulative = **{best_cum.get('cumulative_return_bps', '?')} bps**, "
                     f"Sharpe = {best_cum.get('sharpe_proxy', '?')}")
        lines.append("")

    # EV sizing specific
    ev_entries = [r for r in unified if r["category"] == "ev_sizing"]
    ev_with_sized = [r for r in ev_entries if r.get("sized_sharpe")]
    if ev_with_sized:
        lines += [
            "### EV Sizing Impact",
            "",
        ]
        for r in ev_with_sized:
            lines.append(
                f"- **{r['method']}**: unsized Sharpe={r.get('sharpe_proxy','?')} → "
                f"EV-sized Sharpe={r.get('sized_sharpe','?')}, "
                f"sized avg return={r.get('sized_avg_return_bps','?')} bps, "
                f"sized cumulative={r.get('sized_cumulative_bps','?')} bps"
            )
        lines.append("")

    # Regime switching finding
    if best_regime:
        lines += [
            "### Regime-Switching Result",
            "",
            f"Best regime-switching variant: **{best_regime.get('label', '?')}** "
            f"(Sharpe={best_regime.get('sharpe_proxy', '?')}, "
            f"Hit={best_regime.get('hit_rate', '?')}, "
            f"Avg Return={best_regime.get('avg_return_60m_bps', '?')} bps)",
            "",
        ]

    # EV bucket breakdown
    if ev_buckets:
        lines += [
            "---", "",
            "## EV Bucket Breakdown",
            "",
            "| EV Bucket | N | Hit Rate | Avg Return (bps) |",
            "|-----------|---|----------|------------------|",
        ]
        for b in ev_buckets:
            lines.append(f"| {b.get('ev_bucket','?')} | {b.get('n','?')} | {b.get('hit_rate','?')} | {b.get('avg_return_bps','?')} |")
        lines.append("")

    # Research questions
    lines += [
        "---", "",
        "## Research Questions Answered",
        "",
        "### Q1. Does EV-based sizing outperform confidence-only sizing?",
        "",
    ]
    ev_conf = next((r for r in unified if r["method"] == "rank_filtered_confidence_sized"), None)
    ev_ev = next((r for r in unified if r["method"] == "rank_filtered_ev_sized"), None)
    if ev_conf and ev_ev:
        lines.append(
            f"**Confidence-sized:** avg return = {ev_conf.get('sized_avg_return_bps','?')} bps, "
            f"Sharpe = {ev_conf.get('sized_sharpe','?')}  "
        )
        lines.append(
            f"**EV-sized:** avg return = {ev_ev.get('sized_avg_return_bps','?')} bps, "
            f"Sharpe = {ev_ev.get('sized_sharpe','?')}  "
        )
        if ev_ev.get("sized_sharpe") and ev_conf.get("sized_sharpe"):
            delta = round(ev_ev["sized_sharpe"] - ev_conf["sized_sharpe"], 4)
            direction = "outperforms" if delta > 0 else "underperforms"
            lines.append(f"\n→ EV sizing **{direction}** confidence sizing by {abs(delta)} Sharpe points.")
    lines.append("")

    lines += [
        "### Q2. Does regime-switching improve over static policies?",
        "",
    ]
    regime_entries = [r for r in unified if r["category"] == "regime_switching"]
    static_entries = [r for r in regime_entries if r["method"].startswith("static_")]
    dynamic_entries = [r for r in regime_entries if not r["method"].startswith("static_")]
    if static_entries and dynamic_entries:
        best_static = max(static_entries, key=lambda r: r.get("sharpe_proxy") or 0)
        best_dynamic = max(dynamic_entries, key=lambda r: r.get("sharpe_proxy") or 0)
        lines.append(f"**Best static:** `{best_static['method']}` (Sharpe={best_static.get('sharpe_proxy','?')})")
        lines.append(f"**Best dynamic:** `{best_dynamic['method']}` (Sharpe={best_dynamic.get('sharpe_proxy','?')})")
        if best_dynamic.get("sharpe_proxy") and best_static.get("sharpe_proxy"):
            delta = round(best_dynamic["sharpe_proxy"] - best_static["sharpe_proxy"], 4)
            if delta > 0:
                lines.append(f"\n→ Regime-switching **improves** over static by {delta} Sharpe points.")
            else:
                lines.append(f"\n→ Static policies **outperform** regime-switching by {abs(delta)} Sharpe points on this dataset.")
    lines.append("")

    lines += [
        "### Q3. Overall ranking across all methods?",
        "",
    ]
    if scored:
        ranked = sorted(scored, key=lambda r: r.get("sharpe_proxy") or -999, reverse=True)
        for i, r in enumerate(ranked[:10], 1):
            lines.append(f"{i}. **{r['method']}** ({r['category']}) — Sharpe={r.get('sharpe_proxy','?')}, Hit={r.get('hit_rate','?')}, Avg Ret={r.get('avg_return_bps','?')} bps")
    lines.append("")

    # Charts
    if charts:
        lines += ["---", "", "## Charts", ""]
        for c in charts:
            fname = Path(c).name
            lines.append(f"![{fname}]({fname})")
            lines.append("")

    lines += [
        "---", "",
        "*RESEARCH ONLY — no production execution logic was modified.*",
    ]
    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════
# Main runner
# ═════════════════════════════════════════════════════════════════════

def run_cross_method_comparison() -> dict[str, Any]:
    """Build unified cross-method comparison from all evaluation artifacts."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S")
    logger.info("=== Cross-Method Comparison — start ===")

    # ── Gather all results ───────────────────────────────────────────
    all_rows: list[dict] = []
    ev_buckets: list[dict] = []

    pred = _gather_predictor_methods()
    all_rows.extend(pred)
    logger.info("Predictor methods: %d", len(pred))

    dp = _gather_decision_policies()
    all_rows.extend(dp)
    logger.info("Decision policies: %d", len(dp))

    rgs = _gather_rank_gate_sizing()
    all_rows.extend(rgs)
    logger.info("Rank-gate sizing: %d", len(rgs))

    ev_result = _gather_ev_sizing()
    if isinstance(ev_result, tuple):
        ev_rows, ev_buckets = ev_result
    else:
        ev_rows = ev_result
    all_rows.extend(ev_rows)
    logger.info("EV sizing: %d", len(ev_rows))

    regime_rows, best_regime = _gather_regime_switching()
    all_rows.extend(regime_rows)
    logger.info("Regime switching: %d", len(regime_rows))

    logger.info("Total methods: %d", len(all_rows))

    # ── Charts ───────────────────────────────────────────────────────
    charts = _generate_comparison_charts(all_rows, ev_buckets)
    logger.info("Charts: %d", len(charts))

    # ── Markdown report ──────────────────────────────────────────────
    md = _generate_markdown(all_rows, ev_buckets, best_regime, charts)
    md_path = OUTPUT_DIR / "cross_method_comparison_report.md"
    md_path.write_text(md, encoding="utf-8")
    logger.info("Saved → %s", md_path)

    # ── CSV ──────────────────────────────────────────────────────────
    df = pd.DataFrame(all_rows)
    csv_path = OUTPUT_DIR / "cross_method_comparison.csv"
    df.to_csv(csv_path, index=False)
    logger.info("Saved → %s", csv_path)

    # ── JSON ─────────────────────────────────────────────────────────
    summary = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "total_methods": len(all_rows),
        "categories": {cat: len([r for r in all_rows if r["category"] == cat])
                      for cat in set(r["category"] for r in all_rows)},
        "unified_results": all_rows,
        "ev_bucket_breakdown": ev_buckets,
        "best_regime_variant": best_regime,
        "charts": [str(c) for c in charts],
    }
    _save(summary, OUTPUT_DIR / "cross_method_comparison.json")

    logger.info("=== Cross-Method Comparison — complete ===")
    return summary


if __name__ == "__main__":
    run_cross_method_comparison()
