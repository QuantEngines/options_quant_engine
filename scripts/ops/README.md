# Operational Scripts

This folder contains one-off and operational maintenance scripts that are useful
for diagnostics, backfills, and rollout checks.

## Scripts

- `apply_ml_inference_backfill.py`
  - Retroactively populates missing ML scores in cumulative signals.
  - Run: `.venv/bin/python scripts/ops/apply_ml_inference_backfill.py`

- `diagnose_ml_inference_gap.py`
  - End-to-end diagnosis for ML score coverage and inference pipeline health.
  - Run: `.venv/bin/python scripts/ops/diagnose_ml_inference_gap.py`

- `run_phase0_shadow_verdict.py`
  - Executes Phase 0 shadow comparison (`blended` vs `research_rank_gate`) and emits GO/NO-GO verdict using rollout KPI gates.
  - Run: `.venv/bin/python scripts/ops/run_phase0_shadow_verdict.py`
  - Optional date: `.venv/bin/python scripts/ops/run_phase0_shadow_verdict.py --date YYYY-MM-DD`

- `run_offline_replay_pack_suite.py`
  - Runs offline-only baseline vs candidate pack replay comparisons across rolling windows and writes auditable artifacts under `research/parameter_tuning/offline_replay_runs/`.
  - Includes checkpoint/resume support so evaluations can continue later from exactly where they stopped.
  - Each invocation writes a dated sub-run folder under `subruns/` and appends to `run_history.csv` so prior summaries are never overwritten.
  - Run: `.venv/bin/python scripts/ops/run_offline_replay_pack_suite.py`
  - Custom candidates/windows: `.venv/bin/python scripts/ops/run_offline_replay_pack_suite.py --candidates macro_overlay_v1 overnight_focus_v1 --windows all 30 60 90`
  - Resume prior run: `.venv/bin/python scripts/ops/run_offline_replay_pack_suite.py --resume-dir research/parameter_tuning/offline_replay_runs/suite_YYYYMMDD_HHMMSS`

- `run_guarded_macro_seed_sweep.py`
  - Runs a 10-20 seed guarded sweep on `macro_news.adjustment` threshold/score fields only.
  - Keeps size multipliers/caps frozen at baseline and auto-selects the best non-negative objective-delta candidate if one appears.
  - Writes sweep ledgers plus candidate packs and recommendation reports for every completed seed.
  - Run: `.venv/bin/python scripts/ops/run_guarded_macro_seed_sweep.py`
  - Custom seeds: `.venv/bin/python scripts/ops/run_guarded_macro_seed_sweep.py --seeds 11 13 17 19 23 29 31 37 41 47 59 73`

- `enforce_strict_promotion_gate.py`
  - Blocks candidate approval unless both `objective_score_delta > 0` and replay `robustness_edge_flag == true`.
  - Optionally records manual approval/rejection in promotion state and always writes a decision artifact under `research/parameter_tuning/promotion_gate_decisions/`.
  - Run: `.venv/bin/python scripts/ops/enforce_strict_promotion_gate.py --candidate-pack <pack> --replay-summary-csv research/parameter_tuning/offline_replay_runs/<suite>/candidate_robustness_edge_summary.csv`
  - Record decision in state: `.venv/bin/python scripts/ops/enforce_strict_promotion_gate.py --candidate-pack <pack> --replay-summary-csv <path> --record-manual-approval --reviewer <name>`
