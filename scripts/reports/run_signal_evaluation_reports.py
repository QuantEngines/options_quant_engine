#!/usr/bin/env python3
"""
Signal Evaluation Report Generator
===================================

Generates both daily and cumulative signal evaluation reports
for the options quantitative trading engine.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

def main():
    from research.signal_evaluation.daily_research_report import generate_daily_report

    print("=" * 80)
    print("SIGNAL EVALUATION REPORT GENERATION")
    print("=" * 80)
    print()

    reports_generated = []
    
    # Generate daily report
    print("1. Generating DAILY signal evaluation report...")
    try:
        daily_report_path = generate_daily_report(mode="daily", narrative=False)
        print(f"   ✓ Daily report generated: {daily_report_path}")
        reports_generated.append(("Daily", daily_report_path))
    except Exception as e:
        print(f"   ✗ Error generating daily report: {e}")
        import traceback
        traceback.print_exc()

    print()

    # Generate cumulative report
    print("2. Generating CUMULATIVE signal evaluation report...")
    try:
        cumulative_report_path = generate_daily_report(mode="cumulative", narrative=False)
        print(f"   ✓ Cumulative report generated: {cumulative_report_path}")
        reports_generated.append(("Cumulative", cumulative_report_path))
    except Exception as e:
        print(f"   ✗ Error generating cumulative report: {e}")
        import traceback
        traceback.print_exc()

    print()
    print("=" * 80)
    print("REPORT GENERATION SUMMARY")
    print("=" * 80)
    for report_type, path in reports_generated:
        print(f"{report_type:12} ✓ {path}")
    print("=" * 80)
    
    return len(reports_generated) == 2

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
