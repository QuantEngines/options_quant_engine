#!/usr/bin/env python3
"""Audit documentation PDFs for formatting and rendering quality risks.

This script scans all PDFs under documentation/ and flags common issues:
- Possible math rendering artifacts (raw LaTeX tokens in extracted text)
- Suspicious heading numbering patterns (e.g., 1.2.2)
- Text extraction failures / empty pages
- Replacement-character artifacts

Outputs:
- JSON report
- Markdown summary report
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from pypdf import PdfReader


@dataclass
class PdfIssue:
    path: str
    pages: int
    extracted_chars: int
    raw_math_tokens: int
    suspicious_heading_tokens: int
    repeated_heading_tokens: int
    replacement_chars: int
    has_extraction_failure: bool

    @property
    def issue_count(self) -> int:
        return (
            self.raw_math_tokens
            + self.suspicious_heading_tokens
            + self.repeated_heading_tokens
            + self.replacement_chars
            + (1 if self.has_extraction_failure else 0)
        )


RAW_MATH_PATTERNS = [
    re.compile(r"\$\$"),
    re.compile(r"\\\("),
    re.compile(r"\\\["),
    re.compile(r"\\frac\s*\{"),
    re.compile(r"\\sum\b"),
    re.compile(r"\\alpha\b|\\beta\b|\\gamma\b|\\delta\b|\\sigma\b"),
]

# Matches lines like "1.2.2 Something"; these can be valid, but are flagged for reviewer check.
SUSPICIOUS_HEADING_PATTERN = re.compile(r"(?m)^\s*\d+\.\d+\.\d+\s+\S+")
# Matches lines like "1.2.2" where last two levels repeat (common bad numbering artifact)
REPEATED_HEADING_PATTERN = re.compile(r"(?m)^\s*\d+\.(\d+)\.\1\s+\S+")


def _extract_text_safe(pdf_path: Path) -> tuple[str, int, bool]:
    reader = PdfReader(str(pdf_path))
    parts: list[str] = []
    failed = False
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
            failed = True
        parts.append(text)
    return "\n".join(parts), len(reader.pages), failed


def audit_pdf(pdf_path: Path) -> PdfIssue:
    text, page_count, failed = _extract_text_safe(pdf_path)

    raw_math_hits = sum(len(p.findall(text)) for p in RAW_MATH_PATTERNS)
    suspicious_heading_hits = len(SUSPICIOUS_HEADING_PATTERN.findall(text))
    repeated_heading_hits = len(REPEATED_HEADING_PATTERN.findall(text))
    replacement_chars = text.count("�")

    return PdfIssue(
        path=pdf_path.as_posix(),
        pages=page_count,
        extracted_chars=len(text),
        raw_math_tokens=raw_math_hits,
        suspicious_heading_tokens=suspicious_heading_hits,
        repeated_heading_tokens=repeated_heading_hits,
        replacement_chars=replacement_chars,
        has_extraction_failure=failed,
    )


def build_markdown_report(issues: list[PdfIssue], generated_at: str, root: Path) -> str:
    flagged = [i for i in issues if i.issue_count > 0]
    lines: list[str] = []
    lines.append("# PDF Quality Audit Report")
    lines.append("")
    lines.append(f"Generated: {generated_at}")
    lines.append(f"Root: {root.as_posix()}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Total PDFs audited: {len(issues)}")
    lines.append(f"- PDFs with at least one flag: {len(flagged)}")
    lines.append("")
    lines.append("## Flagged PDFs")
    lines.append("")
    lines.append("| PDF | Pages | Raw Math Tokens | 3-Level Headings | Repeated Headings | Replacement Chars | Extraction Failure |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | --- |")
    for row in sorted(flagged, key=lambda r: r.issue_count, reverse=True):
        lines.append(
            "| "
            f"{row.path} | {row.pages} | {row.raw_math_tokens} | {row.suspicious_heading_tokens} | "
            f"{row.repeated_heading_tokens} | {row.replacement_chars} | {'YES' if row.has_extraction_failure else 'NO'} |"
        )
    if not flagged:
        lines.append("| (none) | 0 | 0 | 0 | 0 | 0 | NO |")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- Raw math token flags usually indicate formulas were printed as plain LaTeX text instead of typeset math.")
    lines.append("- 3-level heading flags are review markers; not all are errors, but repeated patterns like 1.2.2 are often formatting defects.")
    lines.append("- Extraction failures can indicate scanned/image PDFs or malformed text layer.")
    lines.append("")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit documentation PDFs for quality risks.")
    parser.add_argument(
        "--root",
        default="documentation",
        help="Root directory to scan for PDFs (default: documentation)",
    )
    parser.add_argument(
        "--json-out",
        default=None,
        help="Path to JSON output file",
    )
    parser.add_argument(
        "--md-out",
        default=None,
        help="Path to Markdown output file",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    pdf_paths = sorted(root.rglob("*.pdf"))

    issues = [audit_pdf(p) for p in pdf_paths]
    generated_at = datetime.utcnow().isoformat() + "Z"

    if args.json_out:
        out_json = Path(args.json_out)
        out_json.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": generated_at,
            "root": root.as_posix(),
            "total_pdfs": len(issues),
            "flagged_pdfs": sum(1 for i in issues if i.issue_count > 0),
            "rows": [asdict(i) | {"issue_count": i.issue_count} for i in issues],
        }
        out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if args.md_out:
        out_md = Path(args.md_out)
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(build_markdown_report(issues, generated_at, root), encoding="utf-8")

    flagged = [i for i in issues if i.issue_count > 0]
    print(f"Audited PDFs: {len(issues)}")
    print(f"Flagged PDFs: {len(flagged)}")
    if flagged:
        top = sorted(flagged, key=lambda r: r.issue_count, reverse=True)[:10]
        print("Top flagged:")
        for row in top:
            print(
                f"  - {row.path}: flags={row.issue_count} "
                f"(math={row.raw_math_tokens}, h3={row.suspicious_heading_tokens}, "
                f"repeat={row.repeated_heading_tokens}, repl={row.replacement_chars}, "
                f"extract_fail={row.has_extraction_failure})"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
