# Decision Policy Evaluation Report

**Generated:** 2026-03-18T11:54:19.545871
**Dataset size:** 7,404 signals

**Author:** Pramit Dutta  |  **Organization:** Quant Engines

---

## Policy Performance Summary

### agreement_only

- **Allowed:** 54.6191%  |  **Blocked:** 0.1486%

| Decision | N | Hit Rate 60m | Avg Return 60m (bps) | Avg Return 120m (bps) | Avg MFE 60m | Avg MAE 60m |
|----------|---|-------------|---------------------|----------------------|-------------|-------------|
| ALLOW | 4044 | 0.6748 | 10.9172 | 10.9172 | 0.0 | 0.0 |
| DOWNGRADE | 3349 | 0.3538 | -14.0715 | -14.0715 | 0.0 | 0.0 |
| BLOCK | 11 | 0.0 | -164.2 | -164.2 | 0.0 | 0.0 |

**Sizing simulation** (1264 signals):
- Baseline avg: 10.9172 bps  →  Sized avg: 10.9172 bps
- Improvement: 0.0%

**Drawdown proxy (ALLOW'd signals):** total 13799.32 bps, max DD -2325.59 bps

**Rank-bucket performance (ALLOW'd):**

| Bucket | N | Hit Rate 60m | Avg Return 60m (bps) |
|--------|---|-------------|---------------------|
| Q1 | 809 | 0.2609 | -39.8829 |
| Q2 | 813 | 0.5667 | 16.682 |
| Q3 | 805 | 0.5531 | 2.5242 |
| Q4 | 810 | 0.7394 | 19.189 |
| Q5 | 807 | 0.8535 | 28.2232 |

### dual_threshold

- **Allowed:** 48.6629%  |  **Blocked:** 30.3485%

| Decision | N | Hit Rate 60m | Avg Return 60m (bps) | Avg Return 120m (bps) | Avg MFE 60m | Avg MAE 60m |
|----------|---|-------------|---------------------|----------------------|-------------|-------------|
| ALLOW | 3603 | 0.7412 | 18.9838 | 18.9838 | 0.0 | 0.0 |
| DOWNGRADE | 1554 | 0.5391 | 4.8538 | 4.8538 | 0.0 | 0.0 |
| BLOCK | 2247 | 0.2547 | -26.9768 | -26.9768 | 0.0 | 0.0 |

**Sizing simulation** (1105 signals):
- Baseline avg: 18.9838 bps  →  Sized avg: 18.9838 bps
- Improvement: 0.0%

**Drawdown proxy (ALLOW'd signals):** total 20977.13 bps, max DD -931.94 bps

**Rank-bucket performance (ALLOW'd):**

| Bucket | N | Hit Rate 60m | Avg Return 60m (bps) |
|--------|---|-------------|---------------------|
| Q1 | 722 | 0.5366 | 6.3993 |
| Q2 | 719 | 0.625 | -0.0825 |
| Q3 | 724 | 0.5647 | 4.965 |
| Q4 | 717 | 0.7861 | 22.7428 |
| Q5 | 721 | 0.8507 | 27.9301 |

### sizing_simulation

- **Allowed:** 100.0%  |  **Blocked:** 0.0%

| Decision | N | Hit Rate 60m | Avg Return 60m (bps) | Avg Return 120m (bps) | Avg MFE 60m | Avg MAE 60m |
|----------|---|-------------|---------------------|----------------------|-------------|-------------|
| ALLOW | 7404 | 0.5035 | -2.5998 | -2.5998 | 0.0 | 0.0 |

**Sizing simulation** (2701 signals):
- Baseline avg: -2.5998 bps  →  Sized avg: 3.1901 bps
- Improvement: 222.7054%

**Drawdown proxy (ALLOW'd signals):** total -7021.97 bps, max DD -15723.51 bps

**Rank-bucket performance (ALLOW'd):**

| Bucket | N | Hit Rate 60m | Avg Return 60m (bps) |
|--------|---|-------------|---------------------|
| Q1 | 1482 | 0.208 | -36.1464 |
| Q2 | 1480 | 0.3679 | -11.5817 |
| Q3 | 1481 | 0.6212 | 15.1526 |
| Q4 | 1480 | 0.6103 | 12.6031 |
| Q5 | 1481 | 0.835 | 29.3549 |

### rank_filter_bottom_20pct

- **Allowed:** 80.0243%  |  **Blocked:** 19.9757%

| Decision | N | Hit Rate 60m | Avg Return 60m (bps) | Avg Return 120m (bps) | Avg MFE 60m | Avg MAE 60m |
|----------|---|-------------|---------------------|----------------------|-------------|-------------|
| ALLOW | 5925 | 0.6571 | 14.8148 | 14.8148 | 0.0 | 0.0 |
| BLOCK | 1479 | 0.2072 | -36.2012 | -36.2012 | 0.0 | 0.0 |

**Sizing simulation** (1779 signals):
- Baseline avg: 14.8148 bps  →  Sized avg: 14.8148 bps
- Improvement: 0.0%

**Drawdown proxy (ALLOW'd signals):** total 26355.51 bps, max DD -1779.2 bps

**Rank-bucket performance (ALLOW'd):**

| Bucket | N | Hit Rate 60m | Avg Return 60m (bps) |
|--------|---|-------------|---------------------|
| Q1 | 1185 | 0.3567 | -11.3296 |
| Q2 | 1185 | 0.5714 | -0.9311 |
| Q3 | 1186 | 0.5427 | 10.9005 |
| Q4 | 1186 | 0.6752 | 16.0258 |
| Q5 | 1183 | 0.8433 | 30.6079 |

### rank_filter_bottom_30pct

- **Allowed:** 70.0027%  |  **Blocked:** 29.9973%

| Decision | N | Hit Rate 60m | Avg Return 60m (bps) | Avg Return 120m (bps) | Avg MFE 60m | Avg MAE 60m |
|----------|---|-------------|---------------------|----------------------|-------------|-------------|
| ALLOW | 5183 | 0.7097 | 19.3387 | 19.3387 | 0.0 | 0.0 |
| BLOCK | 2221 | 0.2414 | -30.498 | -30.498 | 0.0 | 0.0 |

**Sizing simulation** (1512 signals):
- Baseline avg: 19.3387 bps  →  Sized avg: 19.3387 bps
- Improvement: 0.0%

**Drawdown proxy (ALLOW'd signals):** total 29240.13 bps, max DD -1385.47 bps

**Rank-bucket performance (ALLOW'd):**

| Bucket | N | Hit Rate 60m | Avg Return 60m (bps) |
|--------|---|-------------|---------------------|
| Q1 | 1038 | 0.4242 | -13.4605 |
| Q2 | 1037 | 0.5 | 17.826 |
| Q3 | 1035 | 0.5731 | 8.5545 |
| Q4 | 1036 | 0.7149 | 22.0718 |
| Q5 | 1037 | 0.8454 | 29.3607 |

---

## Regime-Conditional Analysis

### agreement_only

**Macro:**

| Regime | N | Hit Rate 60m | Avg Return 60m (bps) |
|--------|---|-------------|---------------------|
| EVENT_LOCKDOWN | 177 | None | None |
| MACRO_NEUTRAL | 3867 | 0.6748 | 10.9172 |

**Gamma:**

| Regime | N | Hit Rate 60m | Avg Return 60m (bps) |
|--------|---|-------------|---------------------|
| NEGATIVE_GAMMA | 337 | 0.6712 | 4.3363 |
| NEUTRAL_GAMMA | 347 | 0.7273 | 11.5682 |
| POSITIVE_GAMMA | 3360 | 0.6731 | 11.311 |

**Volatility:**

| Regime | N | Hit Rate 60m | Avg Return 60m (bps) |
|--------|---|-------------|---------------------|
| VOL_EXPANSION | 4044 | 0.6748 | 10.9172 |

**Global_Risk:**

| Regime | N | Hit Rate 60m | Avg Return 60m (bps) |
|--------|---|-------------|---------------------|
| EVENT_LOCKDOWN | 177 | None | None |
| GLOBAL_NEUTRAL | 3861 | 0.6749 | 10.3062 |
| VOL_SHOCK | 6 | 0.6667 | 267.7233 |

### dual_threshold

**Macro:**

| Regime | N | Hit Rate 60m | Avg Return 60m (bps) |
|--------|---|-------------|---------------------|
| EVENT_LOCKDOWN | 161 | None | None |
| MACRO_NEUTRAL | 3442 | 0.7412 | 18.9838 |

**Gamma:**

| Regime | N | Hit Rate 60m | Avg Return 60m (bps) |
|--------|---|-------------|---------------------|
| NEGATIVE_GAMMA | 302 | 0.7213 | 11.4962 |
| NEUTRAL_GAMMA | 326 | 0.7805 | 14.3376 |
| POSITIVE_GAMMA | 2975 | 0.7408 | 19.6291 |

**Volatility:**

| Regime | N | Hit Rate 60m | Avg Return 60m (bps) |
|--------|---|-------------|---------------------|
| VOL_EXPANSION | 3603 | 0.7412 | 18.9838 |

**Global_Risk:**

| Regime | N | Hit Rate 60m | Avg Return 60m (bps) |
|--------|---|-------------|---------------------|
| EVENT_LOCKDOWN | 161 | None | None |
| GLOBAL_NEUTRAL | 3438 | 0.7409 | 18.6192 |

### sizing_simulation

**Macro:**

| Regime | N | Hit Rate 60m | Avg Return 60m (bps) |
|--------|---|-------------|---------------------|
| EVENT_LOCKDOWN | 324 | None | None |
| MACRO_NEUTRAL | 7080 | 0.5035 | -2.5998 |

**Gamma:**

| Regime | N | Hit Rate 60m | Avg Return 60m (bps) |
|--------|---|-------------|---------------------|
| NEGATIVE_GAMMA | 1356 | 0.3685 | -19.1665 |
| NEUTRAL_GAMMA | 909 | 0.4334 | -11.9855 |
| POSITIVE_GAMMA | 5139 | 0.5481 | 2.9855 |

**Volatility:**

| Regime | N | Hit Rate 60m | Avg Return 60m (bps) |
|--------|---|-------------|---------------------|
| VOL_EXPANSION | 7404 | 0.5035 | -2.5998 |

**Global_Risk:**

| Regime | N | Hit Rate 60m | Avg Return 60m (bps) |
|--------|---|-------------|---------------------|
| EVENT_LOCKDOWN | 324 | None | None |
| GLOBAL_NEUTRAL | 7068 | 0.5032 | -2.7923 |
| VOL_SHOCK | 12 | 0.6667 | 83.8933 |

### rank_filter_bottom_20pct

**Macro:**

| Regime | N | Hit Rate 60m | Avg Return 60m (bps) |
|--------|---|-------------|---------------------|
| EVENT_LOCKDOWN | 252 | None | None |
| MACRO_NEUTRAL | 5673 | 0.6571 | 14.8148 |

**Gamma:**

| Regime | N | Hit Rate 60m | Avg Return 60m (bps) |
|--------|---|-------------|---------------------|
| NEGATIVE_GAMMA | 877 | 0.5514 | 8.4522 |
| NEUTRAL_GAMMA | 674 | 0.662 | 7.7474 |
| POSITIVE_GAMMA | 4374 | 0.6725 | 16.4769 |

**Volatility:**

| Regime | N | Hit Rate 60m | Avg Return 60m (bps) |
|--------|---|-------------|---------------------|
| VOL_EXPANSION | 5925 | 0.6571 | 14.8148 |

**Global_Risk:**

| Regime | N | Hit Rate 60m | Avg Return 60m (bps) |
|--------|---|-------------|---------------------|
| EVENT_LOCKDOWN | 252 | None | None |
| GLOBAL_NEUTRAL | 5661 | 0.6571 | 14.581 |
| VOL_SHOCK | 12 | 0.6667 | 83.8933 |

### rank_filter_bottom_30pct

**Macro:**

| Regime | N | Hit Rate 60m | Avg Return 60m (bps) |
|--------|---|-------------|---------------------|
| EVENT_LOCKDOWN | 222 | None | None |
| MACRO_NEUTRAL | 4961 | 0.7097 | 19.3387 |

**Gamma:**

| Regime | N | Hit Rate 60m | Avg Return 60m (bps) |
|--------|---|-------------|---------------------|
| NEGATIVE_GAMMA | 707 | 0.625 | 13.3385 |
| NEUTRAL_GAMMA | 577 | 0.7568 | 12.0892 |
| POSITIVE_GAMMA | 3899 | 0.717 | 20.8089 |

**Volatility:**

| Regime | N | Hit Rate 60m | Avg Return 60m (bps) |
|--------|---|-------------|---------------------|
| VOL_EXPANSION | 5183 | 0.7097 | 19.3387 |

**Global_Risk:**

| Regime | N | Hit Rate 60m | Avg Return 60m (bps) |
|--------|---|-------------|---------------------|
| EVENT_LOCKDOWN | 222 | None | None |
| GLOBAL_NEUTRAL | 4950 | 0.7094 | 19.0424 |
| VOL_SHOCK | 11 | 0.8 | 108.646 |

---

## Yearly Stability

### agreement_only

| Year | N | Hit Rate 60m | Avg Return 60m (bps) |
|------|---|-------------|---------------------|
| 2016 | 366 | 0.6378 | 4.6631 |
| 2017 | 432 | 0.7475 | 14.7656 |
| 2018 | 391 | 0.7263 | 14.4844 |
| 2019 | 367 | 0.6239 | 12.84 |
| 2020 | 447 | 0.6867 | 17.8436 |
| 2021 | 491 | 0.6943 | 14.2751 |
| 2022 | 456 | 0.6395 | 9.5414 |
| 2023 | 408 | 0.61 | 6.2681 |
| 2024 | 357 | 0.7288 | 9.4621 |
| 2025 | 329 | 0.6588 | -1.5512 |

### dual_threshold

| Year | N | Hit Rate 60m | Avg Return 60m (bps) |
|------|---|-------------|---------------------|
| 2016 | 318 | 0.7222 | 13.8315 |
| 2017 | 392 | 0.7802 | 17.2568 |
| 2018 | 345 | 0.8095 | 19.6525 |
| 2019 | 327 | 0.6632 | 14.8754 |
| 2020 | 391 | 0.7762 | 34.7467 |
| 2021 | 430 | 0.7784 | 24.1436 |
| 2022 | 411 | 0.7315 | 19.4164 |
| 2023 | 371 | 0.6977 | 13.082 |
| 2024 | 328 | 0.7547 | 14.5408 |
| 2025 | 290 | 0.6447 | 3.8003 |

### sizing_simulation

| Year | N | Hit Rate 60m | Avg Return 60m (bps) |
|------|---|-------------|---------------------|
| 2016 | 738 | 0.4214 | -10.98 |
| 2017 | 744 | 0.4958 | -1.5202 |
| 2018 | 738 | 0.4911 | -9.8421 |
| 2019 | 732 | 0.4312 | -14.1999 |
| 2020 | 750 | 0.5146 | -8.6568 |
| 2021 | 741 | 0.5848 | 5.1581 |
| 2022 | 744 | 0.5684 | 11.7287 |
| 2023 | 735 | 0.4444 | -2.5931 |
| 2024 | 738 | 0.5773 | 4.5656 |
| 2025 | 744 | 0.5 | -0.8539 |

### rank_filter_bottom_20pct

| Year | N | Hit Rate 60m | Avg Return 60m (bps) |
|------|---|-------------|---------------------|
| 2016 | 514 | 0.618 | 7.7585 |
| 2017 | 616 | 0.6438 | 9.9456 |
| 2018 | 582 | 0.695 | 18.1696 |
| 2019 | 570 | 0.6474 | 11.7239 |
| 2020 | 618 | 0.6853 | 21.184 |
| 2021 | 631 | 0.6941 | 16.9837 |
| 2022 | 644 | 0.6968 | 25.4324 |
| 2023 | 618 | 0.6062 | 9.5095 |
| 2024 | 560 | 0.6739 | 15.5946 |
| 2025 | 572 | 0.5828 | 6.676 |

### rank_filter_bottom_30pct

| Year | N | Hit Rate 60m | Avg Return 60m (bps) |
|------|---|-------------|---------------------|
| 2016 | 452 | 0.6757 | 13.8851 |
| 2017 | 554 | 0.6866 | 12.7247 |
| 2018 | 510 | 0.7419 | 21.75 |
| 2019 | 496 | 0.6889 | 14.4096 |
| 2020 | 554 | 0.7283 | 32.42 |
| 2021 | 569 | 0.7475 | 23.9016 |
| 2022 | 561 | 0.7273 | 22.6192 |
| 2023 | 524 | 0.7165 | 15.3303 |
| 2024 | 486 | 0.7215 | 18.8085 |
| 2025 | 477 | 0.6328 | 10.5317 |
