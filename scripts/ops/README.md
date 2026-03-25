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

- `run_runtime_model_refresh.py`
  - Runs both runtime retraining steps in one pass: time-decay half-life fit and score calibrator fit.
  - Evaluates simple promotion gates (`max_decay_fit_mse`, `max_abs_calibration_gap`) and writes an auditable decision artifact.
  - Writes outputs under `documentation/improvement_reports/` and appends to `runtime_model_refresh_history.csv` without overwriting previous runs.
  - Run: `.venv/bin/python scripts/ops/run_runtime_model_refresh.py`
  - Strict gate mode: `.venv/bin/python scripts/ops/run_runtime_model_refresh.py --strict --max-decay-fit-mse 0.45 --max-abs-calibration-gap 0.10`
  - Failure webhook alert: `.venv/bin/python scripts/ops/run_runtime_model_refresh.py --strict --failure-webhook-url https://example.com/hook`
  - Failure notify command: `.venv/bin/python scripts/ops/run_runtime_model_refresh.py --strict --failure-notify-command "osascript -e 'display notification \"Runtime refresh gate failed\" with title \"options_quant_engine\"'"`

- `macos/install_daily_runtime_model_refresh_launchd.sh`
  - Installs a daily macOS LaunchAgent to run runtime refresh automatically at 18:05 local time.
  - Installer: `bash scripts/ops/macos/install_daily_runtime_model_refresh_launchd.sh`
  - Optional Python path override: `bash scripts/ops/macos/install_daily_runtime_model_refresh_launchd.sh /absolute/path/to/python`
  - Optional failure webhook via env before install:
    `export RUNTIME_MODEL_REFRESH_FAILURE_WEBHOOK_URL=https://example.com/hook`
  - Generated LaunchAgent path: `~/Library/LaunchAgents/com.optionsquant.runtime_model_refresh.plist`
