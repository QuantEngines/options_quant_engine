#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_MD="$ROOT_DIR/research/quant_note_trade_signal_logic.md"
STYLE_CSS="$ROOT_DIR/research/quant_note_trade_signal_logic_style.css"
OUTPUT_DIR="$ROOT_DIR/documentation/research_notes"
OUTPUT_HTML="$OUTPUT_DIR/quant_note_trade_signal_logic_polished.html"
OUTPUT_PDF="$OUTPUT_DIR/quant_note_trade_signal_logic_polished.pdf"
CHROME_BIN="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

source "$ROOT_DIR/scripts/activate_pdf_tools.sh" >/dev/null
mkdir -p "$OUTPUT_DIR"

pandoc "$SOURCE_MD" \
  --standalone \
  --from gfm \
  --to html5 \
  --embed-resources \
  --toc \
  --toc-depth=2 \
  --number-sections \
  --css "$STYLE_CSS" \
  -o "$OUTPUT_HTML"

if [ ! -x "$CHROME_BIN" ]; then
  echo "Chrome not found at: $CHROME_BIN" >&2
  exit 1
fi

"$CHROME_BIN" \
  --headless \
  --disable-gpu \
  --no-pdf-header-footer \
  --print-to-pdf="$OUTPUT_PDF" \
  "file://$OUTPUT_HTML"

echo "Rendered:"
echo "  HTML: $OUTPUT_HTML"
echo "  PDF : $OUTPUT_PDF"
