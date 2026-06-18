#!/usr/bin/env python3
"""
Classify SEC UPLOAD comment letters for the main peer-share IV.

The script reads extracted SEC comment-letter text, splits each letter into
comment items, applies the final clean dictionary, and writes letter-level
flags used by the peer IV builder.

Main item rule:

    numerator item =
        equity financing/access term
        AND financing-disclosure context term
        AND NOT compensation/accounting/valuation exclusion term

Denominator item =
        clean equity financing/access term
        OR source-of-funds / external-financing / debt-financing term

No SEC text is downloaded here. Run 01_crawl_sec_upload_comments.py first.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional


def add_local_deps() -> None:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        dep_dir = parent / ".codex_pydeps"
        if dep_dir.exists():
            sys.path.insert(0, str(dep_dir))
            return


add_local_deps()

import pandas as pd


HERE = Path(__file__).resolve()
REPO = HERE.parents[1]
DEFAULT_DICTIONARY = REPO / "dictionary" / "peer_sec_equity_disclosure_dictionary.csv"


def clean_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def split_comment_items(text: str) -> List[str]:
    """Split SEC letters using the same item logic as the research workflow."""
    text = clean_space(text)
    if not text:
        return []

    first_marker = re.search(r"(?<!\d)(1\.|1\))\s+[A-Z0-9]", text)
    text_for_split = text
    if first_marker and first_marker.start() > 0:
        text_for_split = text[max(0, first_marker.start() - 250) :]

    parts = [text_for_split]
    for pat in [
        r"\s(?=(?:\d{1,3}\.|\d{1,3}\))\s+[A-Z0-9])",
        r"\s(?=(?:Comment\s+\d{1,3}\s*[:.-])\s*)",
    ]:
        trial = re.split(pat, text_for_split, flags=re.IGNORECASE)
        trial = [p.strip() for p in trial if len(p.strip()) >= 60]
        if len(trial) > len(parts):
            parts = trial

    if len(parts) == 1 and len(parts[0]) > 6000:
        trial = re.split(
            r"\s(?=(?:Form\s+10-K|Form\s+10-Q|Management.{0,5}s Discussion|Liquidity and Capital Resources|Risk Factors)\b)",
            parts[0],
            flags=re.IGNORECASE,
        )
        trial = [p.strip() for p in trial if len(p.strip()) >= 100]
        if len(trial) > 1:
            parts = trial

    cleaned: List[str] = []
    seen = set()
    for part in parts:
        part = part.strip()
        if len(part) < 80:
            continue
        key = part[:200]
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(part)
    return cleaned if cleaned else [text]


def resolve_text_path(value: object, letters_csv: Path, text_dir: Optional[Path]) -> Optional[Path]:
    if value is None or pd.isna(value):
        return None
    p = Path(str(value))
    if p.is_absolute() and p.exists():
        return p
    if text_dir is not None:
        candidate = text_dir / p.name
        if candidate.exists():
            return candidate
    for base in [letters_csv.parent, letters_csv.parent.parent, REPO]:
        candidate = base / p
        if candidate.exists():
            return candidate
    return p if p.exists() else None


def read_text(path: Optional[Path]) -> str:
    if path is None:
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    if text.lstrip().startswith("%PDF"):
        raise RuntimeError(f"Raw PDF bytes reached classifier: {path}")
    return text


def compile_terms(dictionary_path: Path) -> pd.DataFrame:
    terms = pd.read_csv(dictionary_path, dtype=str).fillna("")
    if terms.empty:
        raise ValueError(f"Dictionary is empty: {dictionary_path}")
    role_cols = [
        "equity_financing_access_signal",
        "financing_disclosure_context_signal",
        "general_financing_disclosure_scope",
        "nonfinancing_compensation_accounting_exclusion",
    ]
    for col in role_cols:
        if col not in terms.columns:
            raise ValueError(f"Dictionary is missing required column: {col}")
        terms[col] = pd.to_numeric(terms[col], errors="coerce").fillna(0).astype(int)
    if "regex" not in terms.columns:
        raise ValueError("Dictionary is missing required column: regex")
    terms["compiled_regex"] = terms["regex"].apply(lambda p: re.compile(str(p), re.IGNORECASE))
    return terms


def any_role_hit(item: str, terms: pd.DataFrame, role_col: str) -> bool:
    role_terms = terms.loc[terms[role_col].eq(1), "compiled_regex"]
    return any(p.search(item or "") for p in role_terms)


def classify_item(item: str, terms: pd.DataFrame) -> Dict[str, int]:
    equity = any_role_hit(item, terms, "equity_financing_access_signal")
    context = any_role_hit(item, terms, "financing_disclosure_context_signal")
    exclusion = any_role_hit(item, terms, "nonfinancing_compensation_accounting_exclusion")
    general_financing_scope = any_role_hit(item, terms, "general_financing_disclosure_scope")
    clean_equity = equity and not exclusion
    numerator = clean_equity and context
    denominator = clean_equity or general_financing_scope
    return {
        "n_CFULLX": int(numerator),
        "n_CFULLX_eq_any": int(clean_equity),
        "n_SRCFUNDS_denominator": int(denominator),
        "n_context": int(context),
        "n_exclusion": int(exclusion),
        "n_general_financing_scope": int(general_financing_scope),
    }


def classify_letters(
    letters_csv: Path,
    dictionary_path: Path,
    outdir: Path,
    text_dir: Optional[Path],
    progress_every: int,
) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    terms = compile_terms(dictionary_path)
    meta_cols = [
        "gvkey",
        "cik10",
        "accession",
        "filing_date_public",
        "comment_year",
        "url",
        "source_doc_type",
        "extraction_method",
        "text_file",
        "text_length",
    ]
    meta = pd.read_csv(letters_csv, dtype={"gvkey": str, "cik10": str}, usecols=lambda c: c in meta_cols, low_memory=False)

    item_rows: List[dict] = []
    letter_rows: List[dict] = []
    start = time.time()
    for i, row in enumerate(meta.itertuples(index=False), 1):
        base = row._asdict()
        text = read_text(resolve_text_path(base.get("text_file", ""), letters_csv, text_dir))
        items = split_comment_items(text)
        sums = {
            "n_CFULLX": 0,
            "n_CFULLX_eq_any": 0,
            "n_SRCFUNDS_denominator": 0,
            "n_context": 0,
            "n_exclusion": 0,
            "n_general_financing_scope": 0,
        }
        for j, item in enumerate(items, 1):
            flags = classify_item(item, terms)
            for key, value in flags.items():
                sums[key] += int(value)
            item_rows.append(
                {
                    **base,
                    "letter_item_id": f"{base.get('accession', '')}__{j:03d}",
                    "item_no": j,
                    "item_text_excerpt": item[:2500],
                    **flags,
                }
            )

        letter_rows.append(
            {
                **base,
                "n_items": len(items),
                **sums,
                "num_CFULLX": float(sums["n_CFULLX"]),
                "num_any_CFULLX": float(sums["n_CFULLX"] > 0),
                "den_CFULLX_SRCFUNDS": float(sums["n_SRCFUNDS_denominator"]),
                "den_any_CFULLX_SRCFUNDS": float(sums["n_SRCFUNDS_denominator"] > 0),
            }
        )
        if progress_every and (i == 1 or i % progress_every == 0):
            elapsed = (time.time() - start) / 60
            print(f"Classified {i:,}/{len(meta):,} letters; elapsed={elapsed:.1f}m", flush=True)

    items = pd.DataFrame(item_rows)
    letters = pd.DataFrame(letter_rows)
    items.to_csv(outdir / "sec_comment_item_equity_disclosure_flags.csv", index=False)
    letters.to_csv(outdir / "sec_comment_letter_equity_disclosure_flags.csv", index=False)
    pd.DataFrame(
        [
            {"role": "equity_financing_access_signal", "n_terms": int(terms["equity_financing_access_signal"].sum())},
            {"role": "financing_disclosure_context_signal", "n_terms": int(terms["financing_disclosure_context_signal"].sum())},
            {"role": "general_financing_disclosure_scope", "n_terms": int(terms["general_financing_disclosure_scope"].sum())},
            {
                "role": "nonfinancing_compensation_accounting_exclusion",
                "n_terms": int(terms["nonfinancing_compensation_accounting_exclusion"].sum()),
            },
            {"role": "all_unique_rows", "n_terms": int(len(terms))},
        ]
    ).to_csv(outdir / "dictionary_role_counts.csv", index=False)
    print(f"Saved {len(letters):,} letter rows and {len(items):,} item rows to {outdir}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--letters-csv", type=Path, required=True)
    parser.add_argument("--dictionary", type=Path, default=DEFAULT_DICTIONARY)
    parser.add_argument("--text-dir", type=Path, default=None)
    parser.add_argument("--outdir", type=Path, default=Path("output/equity_disclosure_letter_flags"))
    parser.add_argument("--progress-every", type=int, default=5000)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    classify_letters(args.letters_csv, args.dictionary, args.outdir, args.text_dir, args.progress_every)


if __name__ == "__main__":
    main()
