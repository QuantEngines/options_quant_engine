# Decision Policy — Cross-Methodology Comparison

**Generated:** 2026-03-18T11:54:19.547680

**Author:** Pramit Dutta  |  **Organization:** Quant Engines

---

| Methodology | N | Hit Rate 60m | Avg Return 60m (bps) | Avg Return 120m (bps) | Avg MFE 60m | Avg MAE 60m |
|-------------|---|-------------|---------------------|----------------------|-------------|-------------|
| Baseline (all signals) | 7404 | 0.5035 | -2.5998 | -2.5998 | 0.0 | 0.0 |
| Baseline (TRADE only) | 2654 | 0.5021 | -2.712 | -2.712 | 0.0 | 0.0 |
| Research Dual-Model (conf ≥ 0.50) | 4044 | 0.6748 | 10.9172 | 10.9172 | 0.0 | 0.0 |
| Policy: agreement_only | 4044 | 0.6748 | 10.9172 | 10.9172 | 0.0 | 0.0 |
| Policy: dual_threshold | 3603 | 0.7412 | 18.9838 | 18.9838 | 0.0 | 0.0 |
| Policy: sizing_simulation | 7404 | 0.5035 | -2.5998 | -2.5998 | 0.0 | 0.0 |
| Policy: rank_filter_bottom_20pct | 5925 | 0.6571 | 14.8148 | 14.8148 | 0.0 | 0.0 |
| Policy: rank_filter_bottom_30pct | 5183 | 0.7097 | 19.3387 | 19.3387 | 0.0 | 0.0 |

---

*Baseline includes all signals; policy rows show only ALLOW'd signals.*