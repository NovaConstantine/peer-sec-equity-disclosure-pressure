#!/usr/bin/env python3
"""
Build the main peer SEC equity disclosure pressure IV.

Main variable:

    FF48_C_SRCFUNDS_firmshare

Robustness variable:

    FF48_CFULLX_SRCFUNDS_lettershare

Timing:

    focal firm previous datadate < peer SEC comment public date <= focal firm current datadate

Peer events are assigned using FF48 peers in the focal firm's prior fiscal year.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, Optional, Sequence, Tuple


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


MAIN_IV = "FF48_C_SRCFUNDS_firmshare"
ROBUST_IV = "FF48_CFULLX_SRCFUNDS_lettershare"
OUTPUT_IVS = [MAIN_IV, ROBUST_IV]


def clean_id(value: object, zfill: Optional[int] = None) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    text = re.sub(r"\.0$", "", text)
    if zfill and text.isdigit():
        return text.zfill(zfill)
    return text


def clean_cik(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = re.sub(r"\D", "", str(value))
    return text.zfill(10) if text else ""


def find_col(df: pd.DataFrame, candidates: Sequence[str], required: bool = True) -> Optional[str]:
    lower = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in lower:
            return lower[cand.lower()]
    if required:
        raise ValueError(f"Missing required column. Tried: {', '.join(candidates)}")
    return None


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() == ".dta":
        if pyreadstat is None:
            raise ImportError("Reading .dta files requires pyreadstat.")
        df, _meta = pyreadstat.read_dta(str(path))
        return df
    return pd.read_csv(path, dtype=str, low_memory=False)


def write_outputs(df: pd.DataFrame, outdir: Path, basename: str, write_dta: bool) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    csv_path = outdir / f"{basename}.csv"
    df.to_csv(csv_path, index=False)
    print(f"Saved CSV: {csv_path}")
    if not write_dta:
        return
    if pyreadstat is None:
        print("Skipping .dta output because pyreadstat is not installed.")
        return
    dta = df.copy()
    for col in dta.columns:
        if dta[col].dtype == "object":
            dta[col] = dta[col].astype(str).str.slice(0, 2045)
    dta_path = outdir / f"{basename}.dta"
    pyreadstat.write_dta(dta, str(dta_path))
    print(f"Saved DTA: {dta_path}")


def normalize_panel(
    panel: pd.DataFrame,
    firm_col: Optional[str],
    year_col: Optional[str],
    datadate_col: Optional[str],
    peer_group_col: str,
) -> pd.DataFrame:
    out = panel.copy()
    firm_col = firm_col or find_col(out, ["gvkey", "firm_id", "permno"])
    year_col = year_col or find_col(out, ["fyear", "fiscal_year", "year"])
    datadate_col = datadate_col or find_col(out, ["datadate"])
    peer_group_col = find_col(out, [peer_group_col])
    cik_col = find_col(out, ["cik10", "cik_string", "cik"], required=False)

    out["gvkey"] = out[firm_col].apply(lambda x: clean_id(x, zfill=6))
    out["fyear"] = pd.to_numeric(out[year_col], errors="coerce").astype("Int64")
    out["datadate"] = pd.to_datetime(out[datadate_col], errors="coerce")
    out["ffi48"] = pd.to_numeric(out[peer_group_col], errors="coerce")
    out["base_fyear"] = (pd.to_numeric(out["fyear"], errors="coerce") - 1).astype("Int64")
    out["base_ffi48"] = out["ffi48"]
    out["cik10"] = out[cik_col].apply(clean_cik) if cik_col else ""
    out = out.sort_values(["gvkey", "fyear", "datadate"]).reset_index(drop=True)
    out["prev_datadate"] = out.groupby("gvkey")["datadate"].shift(1)
    return out


def normalize_letters(path: Path) -> pd.DataFrame:
    letters = pd.read_csv(path, dtype={"gvkey": str, "cik10": str}, low_memory=False)
    gvkey_col = find_col(letters, ["gvkey", "firm_id"])
    date_col = find_col(letters, ["filing_date_public", "filingDate", "public_date"])
    letters["gvkey"] = letters[gvkey_col].apply(lambda x: clean_id(x, zfill=6))
    letters["filing_date_public"] = pd.to_datetime(letters[date_col], errors="coerce")
    for col in ["num_any_CFULLX", "den_any_CFULLX_SRCFUNDS"]:
        if col not in letters.columns:
            raise ValueError(f"Missing required letter flag column: {col}")
        letters[col] = pd.to_numeric(letters[col], errors="coerce").fillna(0.0)
    return letters.dropna(subset=["gvkey", "filing_date_public"]).copy()


def load_compustat(path: Optional[Path]) -> Optional[pd.DataFrame]:
    if path is None:
        return None
    comp = read_table(path)
    gvkey_col = find_col(comp, ["gvkey", "GVKEY"])
    year_col = find_col(comp, ["fyear", "fiscal_year", "year"])
    out = comp.copy()
    out["gvkey"] = out[gvkey_col].apply(lambda x: clean_id(x, zfill=6))
    out["base_fyear"] = pd.to_numeric(out[year_col], errors="coerce").astype("Int64")
    return out[["gvkey", "base_fyear"]].dropna(subset=["gvkey", "base_fyear"])


def build_membership(panel: pd.DataFrame, compustat: Optional[pd.DataFrame]) -> pd.DataFrame:
    panel_members = (
        panel[["gvkey", "fyear", "ffi48"]]
        .dropna(subset=["gvkey", "fyear", "ffi48"])
        .drop_duplicates()
        .rename(columns={"fyear": "base_fyear"})
    )
    panel_members["base_fyear"] = pd.to_numeric(panel_members["base_fyear"], errors="coerce").astype("Int64")
    if compustat is None:
        return panel_members

    # Match the research workflow: use Compustat gvkey-year rows as the peer
    # universe, then attach FF48 from the regression panel for the same base year.
    membership = compustat.merge(panel_members, on=["gvkey", "base_fyear"], how="left")
    return membership.dropna(subset=["gvkey", "base_fyear"])


def build_event_groups(letters: pd.DataFrame, membership: pd.DataFrame) -> Dict[Tuple[object, object], pd.DataFrame]:
    event_cols = ["gvkey", "filing_date_public", "num_any_CFULLX", "den_any_CFULLX_SRCFUNDS"]
    events = membership.merge(letters[event_cols], on="gvkey", how="inner")
    return {key: grp[event_cols].copy() for key, grp in events.groupby(["base_fyear", "ffi48"], sort=False)}


def safe_share(num: float, den: float) -> float:
    return 0.0 if den <= 0 else float(num) / float(den)


def add_peer_variables(panel: pd.DataFrame, letters: pd.DataFrame, compustat: Optional[pd.DataFrame]) -> pd.DataFrame:
    out = panel.copy()
    membership = build_membership(out, compustat)
    event_groups = build_event_groups(letters, membership)

    main = pd.Series(np.nan, index=out.index, dtype=float)
    robust = pd.Series(np.nan, index=out.index, dtype=float)
    audit = {
        "peer_CFULLX_num_firms": pd.Series(np.nan, index=out.index, dtype=float),
        "peer_CFULLX_num_letters": pd.Series(np.nan, index=out.index, dtype=float),
        "peer_SRCFUNDS_denominator_firms": pd.Series(np.nan, index=out.index, dtype=float),
        "peer_SRCFUNDS_denominator_letters": pd.Series(np.nan, index=out.index, dtype=float),
    }

    grouped = out.dropna(subset=["base_fyear", "base_ffi48"]).groupby(["base_fyear", "base_ffi48"], sort=False)
    for key, idxs in grouped.groups.items():
        events = event_groups.get(key)
        if events is None or events.empty:
            for series in [main, robust, *audit.values()]:
                series.loc[idxs] = 0.0
            continue

        dates = events["filing_date_public"].to_numpy(dtype="datetime64[ns]")
        gvkeys = events["gvkey"].astype(str).to_numpy()
        num_any = events["num_any_CFULLX"].to_numpy(dtype=float) > 0
        den_any = events["den_any_CFULLX_SRCFUNDS"].to_numpy(dtype=float) > 0

        sub = out.loc[idxs, ["gvkey", "prev_datadate", "datadate"]]
        for ridx, row in sub.iterrows():
            if pd.isna(row["prev_datadate"]) or pd.isna(row["datadate"]):
                continue
            in_window = (dates > np.datetime64(row["prev_datadate"])) & (dates <= np.datetime64(row["datadate"]))
            is_peer = gvkeys != str(row["gvkey"])
            mask = in_window & is_peer
            if not mask.any():
                main.at[ridx] = 0.0
                robust.at[ridx] = 0.0
                for series in audit.values():
                    series.at[ridx] = 0.0
                continue

            peer_gv = gvkeys[mask]
            num_firms = float(len(set(peer_gv[num_any[mask]])))
            den_firms = float(len(set(peer_gv[den_any[mask]])))
            num_letters = float(num_any[mask].sum())
            den_letters = float(den_any[mask].sum())

            main.at[ridx] = safe_share(num_firms, den_firms)
            robust.at[ridx] = safe_share(num_letters, den_letters)
            audit["peer_CFULLX_num_firms"].at[ridx] = num_firms
            audit["peer_CFULLX_num_letters"].at[ridx] = num_letters
            audit["peer_SRCFUNDS_denominator_firms"].at[ridx] = den_firms
            audit["peer_SRCFUNDS_denominator_letters"].at[ridx] = den_letters

    out[MAIN_IV] = main.fillna(0.0)
    out["FF48_CFULLX_SRCFUNDS_firmshare"] = out[MAIN_IV]
    out[ROBUST_IV] = robust.fillna(0.0)
    for name, series in audit.items():
        out[name] = series.fillna(0.0)
    return out


def write_distribution(df: pd.DataFrame, cols: Iterable[str], outdir: Path) -> None:
    rows = []
    for col in cols:
        s = pd.to_numeric(df[col], errors="coerce")
        rows.append(
            {
                "variable": col,
                "n": int(s.notna().sum()),
                "nonzero": int(s.fillna(0).ne(0).sum()),
                "mean": float(s.mean()) if s.notna().any() else np.nan,
                "p50": float(s.quantile(0.50)) if s.notna().any() else np.nan,
                "p90": float(s.quantile(0.90)) if s.notna().any() else np.nan,
                "p95": float(s.quantile(0.95)) if s.notna().any() else np.nan,
                "p99": float(s.quantile(0.99)) if s.notna().any() else np.nan,
                "min": float(s.min()) if s.notna().any() else np.nan,
                "max": float(s.max()) if s.notna().any() else np.nan,
            }
        )
    pd.DataFrame(rows).to_csv(outdir / "peer_sec_equity_disclosure_pressure_distribution.csv", index=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--letter-flags", type=Path, required=True)
    parser.add_argument("--compustat", type=Path, default=None)
    parser.add_argument("--outdir", type=Path, default=Path("output/peer_variables"))
    parser.add_argument("--firm-col", default=None)
    parser.add_argument("--year-col", default=None)
    parser.add_argument("--datadate-col", default=None)
    parser.add_argument("--peer-group-col", default="ffi48")
    parser.add_argument("--no-dta", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    panel = normalize_panel(read_table(args.panel), args.firm_col, args.year_col, args.datadate_col, args.peer_group_col)
    letters = normalize_letters(args.letter_flags)
    compustat = load_compustat(args.compustat)
    out = add_peer_variables(panel, letters, compustat)
    args.outdir.mkdir(parents=True, exist_ok=True)
    write_distribution(out, OUTPUT_IVS, args.outdir)
    write_outputs(out, args.outdir, "peer_sec_equity_disclosure_pressure_panel", write_dta=not args.no_dta)


if __name__ == "__main__":
    main()
