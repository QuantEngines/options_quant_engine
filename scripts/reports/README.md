# Reporting Scripts

This folder contains signal-evaluation reporting scripts that were previously
kept as loose repository-root utilities.

## Files

- run_signal_evaluation_reports.py: generates daily and cumulative signal reports.
- generate_signal_report_pdfs_pandoc.py: converts signal reports to PDF using pandoc.
- generate_signal_report_pdfs_fpdf.py: converts signal reports to PDF using fpdf2.

## Output Location

These scripts write report artifacts under:

- the local report archive directory configured in the script constants.

This keeps report generation code grouped under scripts/ while preserving output
artifacts in the local reports area.
