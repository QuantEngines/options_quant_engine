"""
Math notation standardization for all documentation markdown files.
Applies consistent operator, abbreviation, and subscript notation across
the 5 math-bearing documentation sources.
"""
import re
import pathlib

ROOT = pathlib.Path("documentation")

FILES = {
    "academic":  ROOT / "system_docs/options_quant_engine_academic_paper.md",
    "monograph": ROOT / "system_docs/options_quant_engine_system_monograph.md",
    "thesis":    ROOT / "research_notes/options_quant_engine_thesis.md",
    "research":  ROOT / "system_docs/options_quant_engine_research_paper.md",
    "handbook":  ROOT / "system_docs/options_quant_engine_terminology_and_math_handbook.md",
}


def apply_shared_fixes(text: str) -> str:
    """Fixes that apply across ALL math documents."""

    # 1. \text{sign} -> \operatorname{sign}  (sign is a math operator, not prose text)
    text = text.replace(r'\text{sign}', r'\operatorname{sign}')

    # 2. OI_ (undecorated) -> \mathrm{OI}_  (OI is a multi-letter abbreviation)
    #    Only applies OUTSIDE fenced code blocks (``` ... ```) to avoid mangling pseudo-code.
    def fix_oi_outside_codeblocks(src: str) -> str:
        parts = re.split(r'(```.*?```)', src, flags=re.DOTALL)
        result = []
        for i, part in enumerate(parts):
            if i % 2 == 0:
                # Prose / math section — apply the fix
                part = re.sub(r'(?<!\\mathrm\{)(?<!\{)OI_', r'\\mathrm{OI}_', part)
            # Odd parts are fenced code blocks — leave untouched
            result.append(part)
        return ''.join(result)
    text = fix_oi_outside_codeblocks(text)

    # 3. \text{GEX} -> \mathrm{GEX}  (abbreviation, not prose text)
    text = text.replace(r'\text{GEX}', r'\mathrm{GEX}')

    # 4. \sigma_{ATM} -> \sigma_{\mathrm{ATM}}  (ATM is an abbreviation)
    text = text.replace(r'\sigma_{ATM}', r'\sigma_{\mathrm{ATM}}')

    # 5. subscript {min} -> {\min} (use LaTeX min operator for subscript labels)
    #    Handles: f_{min}, r_{min}, n_{min}, p_{min}
    text = re.sub(r'([a-zA-Z])_\{min\}', lambda m: m.group(1) + r'_{\min}', text)

    # 6. \text{frequency}( -> \operatorname{frequency}(
    text = text.replace(r'\text{frequency}(', r'\operatorname{frequency}(')

    # 7. \text{robustness}( -> \operatorname{robustness}(
    text = text.replace(r'\text{robustness}(', r'\operatorname{robustness}(')

    # 8. \text{sample}( -> \operatorname{sample}(  (used as a function of theta)
    text = text.replace(r'\text{sample}(', r'\operatorname{sample}(')

    # 9. \text{sample count}( -> \operatorname{sample\,count}(
    text = text.replace(r'\text{sample count}(', r'\operatorname{sample\,count}(')

    return text


def apply_monograph_fixes(text: str) -> str:
    """Notation fixes specific to the system monograph."""

    # 1. Bare GEX_ (not already decorated) -> \mathrm{GEX}_
    text = re.sub(r'(?<!\\mathrm\{)(?<!\\text\{)(?<!\\mathit\{)GEX_',
                  r'\\mathrm{GEX}_', text)

    # 2. \text{Vega} \, \Delta \sigma -> \nu \, \Delta \sigma
    #    (vega is the Greek letter nu in all other documents)
    text = text.replace(r'\text{Vega} \, \Delta \sigma', r'\nu \, \Delta \sigma')

    # 3. J(\theta) -> \mathcal{J}(\theta)  (calligraphic J for objective, consistent with other files)
    #    Only standalone J not already preceded by a backslash command
    text = re.sub(r'(?<![\\A-Za-z{}])J\(\\theta\)', r'\\mathcal{J}(\\theta)', text)

    # 4. \sigma^2/2 inside d_1 formula -> \tfrac{1}{2}\sigma^2  (match other documents)
    text = text.replace(r'+ \sigma^2/2)', r'+ \tfrac{1}{2}\sigma^2)')

    # 5. \text{clip} -> \operatorname{clip}  (already done in handbook, fix monograph)
    text = text.replace(r'\text{clip}', r'\operatorname{clip}')

    return text


def apply_thesis_research_fixes(text: str) -> str:
    """Notation fixes for thesis and research paper."""

    # \hat{\sigma}_{realized} -> \hat{\sigma}_{\mathrm{realized}}  (label, not variable)
    text = text.replace(r'\hat{\sigma}_{realized}', r'\hat{\sigma}_{\mathrm{realized}}')

    return text


def main():
    for name, path in FILES.items():
        if not path.exists():
            print(f"MISSING: {path}")
            continue

        original = path.read_text()
        modified = apply_shared_fixes(original)

        if name == "monograph":
            modified = apply_monograph_fixes(modified)

        if name in ("thesis", "research"):
            modified = apply_thesis_research_fixes(modified)

        if modified != original:
            # Show changed lines
            orig_lines = original.splitlines()
            mod_lines = modified.splitlines()
            diffs = [(i + 1, ol, ml) for i, (ol, ml) in enumerate(zip(orig_lines, mod_lines)) if ol != ml]
            if len(orig_lines) != len(mod_lines):
                print(f"  WARNING: line count changed ({len(orig_lines)} -> {len(mod_lines)})")
            print(f"\nMODIFIED: {name} ({path.name})  [{len(diffs)} line(s) changed]")
            for lineno, old, new in diffs:
                print(f"  L{lineno:4d}  OLD: {old}")
                print(f"         NEW: {new}")
            path.write_text(modified)
            print(f"  -> Written.")
        else:
            print(f"NO CHANGE: {name} ({path.name})")


if __name__ == "__main__":
    main()
