#!/usr/bin/env python3
"""
Build Peer SEC Equity Disclosure Pressure variables.

Input:
  1) a user firm-year panel with CIK, year, firm id, and industry columns;
  2) firm-year SEC comment-letter topic variables created by
     02_process_sec_comment_letters_for_fce_iv.py.

Output:
  the original firm-year panel plus lagged leave-one-out peer SEC disclosure
  pressure variables. This script stops after writing the generated variables.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Tuple


def add_local_deps() -> None:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        dep_dir = parent / ".codex_pydeps"
        if dep_dir.exists():
            sys.path.insert(0, str(dep_dir))
            return


add_local_deps()

import numpy as np
import pandas as pd

try:
    import pyreadstat
except Exception:  # pragma: no cover
    pyreadstat = None


PACKAGE = Path(__file__).resolve().parents[1]
DEFAULT_PANEL = PACKAGE / "data" / "firm_year_panel.csv"
DEFAULT_TOPIC = PACKAGE / "output" / "topic_classifier" / "sec_comment_firmyear_fce_topic.csv"
DEFAULT_OUTDIR = PACKAGE / "output" / "peer_variables"
DEFAULT_TOPIC_VAR = "own_eq_any_minus_debt_fce_broad"


def clean_cik(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    text = re.sub(r"\.0$", "", text)
    text = re.sub(r"\D", "", text)
    return text.zfill(10) if text else ""


def clean_id(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    text = re.sub(r"\.0$", "", text)
    return text


def make_sic3(value: object) -> float:
    if value is None or pd.isna(value):
        return np.nan
    digits = re.sub(r"\D", "", str(value))
    if not digits:
        return np.nan
    return int(digits[:3]) if len(digits) >= 3 else np.nan


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".dta":
        if pyreadstat is None:
            raise ImportError("Reading .dta files requires pyreadstat. Install requirements.txt.")
        df, _meta = pyreadstat.read_dta(str(path))
        return df
    if suffix in {".csv", ".txt"}:
        return pd.read_csv(path, dtype=str)
    raise ValueError(f"Unsupported file type: {path.suffix}. Use .csv or .dta.")


def write_outputs(df: pd.DataFrame, outdir: Path, basename: str, write_dta: bool) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    csv_path = outdir / f"{basename}.csv"
    df.to_csv(csv_path, index=False)
    print(f"Saved CSV: {csv_path}")

    if not write_dta:
        return
    dta_path = outdir / f"{basename}.dta"
    dta_df = df.copy()
    for col in dta_df.columns:
        if dta_df[col].dtype == "object":
            dta_df[col] = dta_df[col].astype(str)
    try:
        dta_df.to_stata(dta_path, write_index=False, version=118)
        print(f"Saved Stata: {dta_path}")
    except Exception as exc:
        print(f"Warning: could not write Stata file ({exc}). CSV output was saved.")


def find_first_column(df: pd.DataFrame, candidates: List[str], label: str) -> str:
    for col in candidates:
        if col in df.columns:
            return col
    raise ValueError(f"No {label} column found. Tried: {candidates}")


def prepare_panel(
    panel: pd.DataFrame,
    cik_cols: List[str],
    year_col: str,
    firm_id_col: str,
    peer_groups: List[str],
) -> Tuple[pd.DataFrame, str]:
    out = panel.copy()

    cik10 = pd.Series([""] * len(out), index=out.index, dtype=object)
    for col in cik_cols:
        if col not in out.columns:
            continue
        candidate = out[col].apply(clean_cik)
        missing = cik10.eq("")
        cik10.loc[missing] = candidate.loc[missing]
    if cik10.eq("").all():
        raise ValueError(f"No valid CIK found. Tried columns: {cik_cols}")
    out["cik10"] = cik10

    if not year_col:
        year_col = find_first_column(out, ["fyear", "fiscal_year", "year"], "year")
    out["fyear"] = pd.to_numeric(out[year_col], errors="coerce").astype("Int64")
    out = out[out["fyear"].notna()].copy()

    if not firm_id_col:
        firm_id_col = "gvkey" if "gvkey" in out.columns else "cik10"
    if firm_id_col not in out.columns:
        raise ValueError(f"Firm id column not found: {firm_id_col}")
    out["_firm_id"] = out[firm_id_col].apply(clean_id)
    empty_id = out["_firm_id"].eq("")
    out.loc[empty_id, "_firm_id"] = out.loc[empty_id, "cik10"]

    if "sic3" in peer_groups and "sic3" not in out.columns and "sic" in out.columns:
        out["sic3"] = out["sic"].apply(make_sic3)

    missing_groups = [g for g in peer_groups if g not in out.columns]
    if missing_groups:
        raise ValueError(f"Peer-group columns missing from panel: {missing_groups}")

    return out, firm_id_col


def load_topic(topic_path: Path, topic_var: str) -> pd.DataFrame:
    topic = pd.read_csv(topic_path, dtype={"cik10": str})
    if "cik10" not in topic.columns:
        raise ValueError("Topic file must contain cik10.")
    if "comment_year" not in topic.columns:
        raise ValueError("Topic file must contain comment_year.")
    if topic_var not in topic.columns:
        raise ValueError(f"Topic variable missing from topic file: {topic_var}")

    topic["cik10"] = topic["cik10"].apply(clean_cik)
    topic["fyear"] = pd.to_numeric(topic["comment_year"], errors="coerce").astype("Int64")
    topic[topic_var] = pd.to_numeric(topic[topic_var], errors="coerce").fillna(0.0)
    return topic


def safe_group_name(group_col: str) -> str:
    return {"ffi48": "ff48", "sic3": "sic3"}.get(group_col, re.sub(r"[^A-Za-z0-9_]", "_", group_col)[:12])


def build_peer_variables(
    panel: pd.DataFrame,
    topic: pd.DataFrame,
    topic_var: str,
    peer_groups: List[str],
) -> Tuple[pd.DataFrame, List[str]]:
    topic_cols = [c for c in topic.columns if c not in {"comment_year"}]
    topic_keep = topic[topic_cols].copy()
    merged = panel.merge(topic_keep, on=["cik10", "fyear"], how="left", suffixes=("", "_sec"))

    topic_vars = [c for c in topic_keep.columns if c not in {"cik10", "fyear"}]
    for col in topic_vars:
        if pd.api.types.is_numeric_dtype(merged[col]):
            merged[col] = merged[col].fillna(0.0)

    out_vars: List[str] = []
    for group_col in peer_groups:
        group_name = safe_group_name(group_col)
        same_year_peer = f"_same_year_peer_{group_name}"
        final_var = f"peer_sec_equity_pressure_{group_name}"

        group = merged.groupby([group_col, "fyear"], dropna=False)
        group_sum = group[topic_var].transform("sum")
        group_n = group[topic_var].transform("count")
        merged[same_year_peer] = (group_sum - merged[topic_var]) / (group_n - 1)
        merged.loc[group_n <= 1, same_year_peer] = np.nan

        lag_df = merged[["_firm_id", "fyear", same_year_peer]].copy()
        lag_df["fyear"] = lag_df["fyear"] + 1
        lag_df = lag_df.rename(columns={same_year_peer: final_var})
        merged = merged.merge(lag_df, on=["_firm_id", "fyear"], how="left")
        merged = merged.drop(columns=[same_year_peer])
        out_vars.append(final_var)

    return merged, out_vars


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", default=str(DEFAULT_PANEL), help="Firm-year panel (.csv or .dta).")
    parser.add_argument("--topic", default=str(DEFAULT_TOPIC), help="Firm-year topic CSV from script 02.")
    parser.add_argument("--outdir", default=str(DEFAULT_OUTDIR), help="Output directory.")
    parser.add_argument("--topic-var", default=DEFAULT_TOPIC_VAR, help="Firm-year SEC topic variable used to build peer pressure.")
    parser.add_argument("--peer-groups", nargs="*", default=["ffi48"], help="Industry/group columns used for leave-one-out peers.")
    parser.add_argument("--cik-cols", nargs="*", default=["cik10", "cik_string", "cik"], help="Candidate CIK columns, in priority order.")
    parser.add_argument("--year-col", default="", help="Panel fiscal-year column. If omitted, tries fyear, fiscal_year, year.")
    parser.add_argument("--firm-id-col", default="", help="Firm identifier column. If omitted, tries gvkey, then cik10.")
    parser.add_argument("--basename", default="peer_sec_equity_disclosure_pressure_panel", help="Output file basename.")
    parser.add_argument("--no-dta", action="store_true", help="Only write CSV output.")
    args = parser.parse_args()

    panel = read_table(Path(args.panel))
    panel, firm_id_col = prepare_panel(
        panel=panel,
        cik_cols=args.cik_cols,
        year_col=args.year_col,
        firm_id_col=args.firm_id_col,
        peer_groups=args.peer_groups,
    )
    topic = load_topic(Path(args.topic), args.topic_var)
    out, peer_vars = build_peer_variables(panel, topic, args.topic_var, args.peer_groups)
    out = out.drop(columns=["_firm_id"], errors="ignore")

    write_outputs(out, Path(args.outdir), args.basename, write_dta=not args.no_dta)
    print(f"Panel rows: {len(out):,}")
    print(f"Firm id column: {firm_id_col if firm_id_col else 'cik10'}")
    print("Peer variables:")
    for var in peer_vars:
        print(f"  {var}")


if __name__ == "__main__":
    main()
