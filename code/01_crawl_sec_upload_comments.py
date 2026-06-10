#!/usr/bin/env python3
"""
Crawl SEC-originated comment letters (UPLOAD) for a sample of CIKs.

The crawler saves the raw SEC filing document and a machine-readable text file.
PDF letters are extracted with pdfminer.six; TXT/HTML letters are decoded and
HTML-stripped directly.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import time
from io import BytesIO
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def add_local_deps() -> None:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        dep_dir = parent / ".codex_pydeps"
        if dep_dir.exists():
            sys.path.insert(0, str(dep_dir))
            return


add_local_deps()

import pandas as pd

try:
    from pdfminer.high_level import extract_text as pdf_extract_text
except Exception:  # pragma: no cover
    pdf_extract_text = None

try:
    import pyreadstat
except Exception:  # pragma: no cover
    pyreadstat = None


LIQ_PATTERNS = [
    r"\bliquidity\b",
    r"\bcapital resources\b",
    r"\bmanagement'?s discussion and analysis\b",
    r"\bMD&A\b",
    r"\bcash requirements?\b",
    r"\bcash flows?\b",
    r"\bworking capital\b",
    r"\bsources and uses of cash\b",
    r"\bfunding\b",
    r"\bfinancing arrangements?\b",
    r"\bdebt covenants?\b",
    r"\bgoing concern\b",
    r"\bknown trends?\b",
    r"\bknown uncertainties\b",
    r"\bshort-term liquidity\b",
    r"\blong-term liquidity\b",
]

EQUITY_PATTERNS = [
    r"\bequity financing\b",
    r"\bcommon stock\b",
    r"\bpublic offering\b",
    r"\bregistered offering\b",
    r"\bfollow-on offering\b",
    r"\bsecondary offering\b",
    r"\bshelf registration\b",
    r"\bat-the-market\b",
    r"\bATM program\b",
    r"\bsale of shares\b",
    r"\bissue shares\b",
    r"\bissuance of shares\b",
    r"\braise capital\b",
    r"\bcapital markets\b",
    r"\bdilution\b",
    r"\bequity securities\b",
    r"\bsale of common stock\b",
    r"\bissuance of common stock\b",
]

ANNUAL_REVIEW_PATTERNS = [
    r"\bForm\s+10-K\b",
    r"\b10-K\b",
    r"\bannual report\b",
]

FILING_COLUMNS = [
    "gvkey",
    "cik10",
    "form",
    "accession",
    "filing_date_public",
    "comment_year",
    "reportDate",
    "primary_doc",
    "url",
    "source_doc_type",
    "extraction_method",
    "raw_file",
    "text_file",
    "text_length",
    "text_extraction_error",
    "text_starts_raw_pdf",
    "liq_comment",
    "equity_liq_comment",
    "annual_related",
    "n_liq_keyword_hits",
    "n_equity_keyword_hits",
    "n_annual_keyword_hits",
]

FIRMYEAR_COLUMNS = [
    "cik10",
    "comment_year",
    "gvkey",
    "n_upload",
    "n_liq_comment",
    "n_equity_liq_comment",
    "n_annual_related",
    "total_text_length",
    "own_liq_comment",
    "own_equity_liq_comment",
    "own_annual_related_comment",
]


def pad_cik(cik: object) -> str:
    if pd.isna(cik):
        return ""
    text = str(cik).strip()
    text = re.sub(r"\.0$", "", text)
    text = re.sub(r"\D", "", text)
    return text.zfill(10) if text else ""


def request_bytes(
    url: str,
    user_agent: str,
    sleep: float,
    max_retries: int = 3,
) -> Tuple[bytes, str]:
    headers = {
        "User-Agent": user_agent,
        "Accept-Encoding": "identity",
        "Host": re.sub(r"^https?://([^/]+).*", r"\1", url),
    }
    last_error = ""
    for attempt in range(max_retries):
        time.sleep(sleep * (attempt + 1))
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=45) as response:
                return response.read(), ""
        except HTTPError as exc:
            last_error = f"HTTP {exc.code}"
            if exc.code not in {403, 429, 500, 502, 503, 504}:
                break
            time.sleep(2.0 * (attempt + 1))
        except URLError as exc:
            last_error = f"URL error: {exc.reason}"
            time.sleep(2.0 * (attempt + 1))
        except TimeoutError:
            last_error = "timeout"
            time.sleep(2.0 * (attempt + 1))
    return b"", last_error


def fetch_json(
    url: str,
    user_agent: str,
    sleep: float,
    max_retries: int = 3,
) -> Tuple[Optional[Dict], str]:
    payload, error = request_bytes(url, user_agent, sleep, max_retries)
    if not payload:
        return None, error
    try:
        return json.loads(payload.decode("utf-8")), ""
    except json.JSONDecodeError as exc:
        return None, f"JSON decode error: {exc}"


def strip_html(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw)
    raw = re.sub(r"(?is)<br\s*/?>", " ", raw)
    raw = re.sub(r"(?is)</p\s*>", " ", raw)
    raw = re.sub(r"(?is)<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    raw = re.sub(r"\s+", " ", raw)
    return raw.strip()


def decode_text_payload(payload: bytes) -> str:
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            return payload.decode(enc, errors="ignore")
        except Exception:
            continue
    return payload.decode("utf-8", errors="ignore")


def source_doc_type(url: str, primary_doc: str, payload: bytes) -> str:
    name = f"{url} {primary_doc}".lower()
    head = payload[:4096].lstrip().lower()
    if payload[:5] == b"%PDF-" or ".pdf" in name:
        return "pdf"
    if any(ext in name for ext in [".htm", ".html"]) or b"<html" in head or b"<body" in head:
        return "html"
    return "text"


def text_starts_raw_pdf(text: str) -> int:
    return int((text or "").lstrip().startswith("%PDF"))


def reusable_existing_text(text_path: Path) -> Optional[str]:
    if not text_path.exists():
        return None
    text = text_path.read_text(encoding="utf-8", errors="ignore")
    if not text.strip() or text_starts_raw_pdf(text):
        return None
    return text


def extract_document_text(payload: bytes, url: str, primary_doc: str) -> Dict[str, object]:
    doc_type = source_doc_type(url, primary_doc, payload)
    method = ""
    error = ""
    text = ""

    if doc_type == "pdf":
        method = "pdfminer.six"
        if pdf_extract_text is None:
            error = "pdfminer.six is not installed"
        else:
            try:
                text = pdf_extract_text(BytesIO(payload)) or ""
            except Exception as exc:
                error = f"pdf extraction failed: {exc}"
    else:
        method = "decode_strip_html" if doc_type == "html" else "decode_text"
        text = decode_text_payload(payload)
        if doc_type == "html":
            text = strip_html(text)

    text = re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()
    starts_raw_pdf = text_starts_raw_pdf(text)
    if starts_raw_pdf:
        error = "; ".join([e for e in [error, "extracted text starts with raw PDF marker"] if e])
        text = ""
    if doc_type == "pdf" and not text:
        error = "; ".join([e for e in [error, "empty PDF text extraction"] if e])

    return {
        "text": text,
        "source_doc_type": doc_type,
        "extraction_method": method,
        "text_extraction_error": error,
        "text_starts_raw_pdf": starts_raw_pdf,
    }


def fetch_document_text(
    url: str,
    primary_doc: str,
    user_agent: str,
    sleep: float,
    max_retries: int = 3,
) -> Tuple[bytes, Dict[str, object]]:
    payload, error = request_bytes(url, user_agent, sleep, max_retries)
    if not payload:
        return b"", {
            "text": "",
            "source_doc_type": source_doc_type(url, primary_doc, b""),
            "extraction_method": "",
            "text_extraction_error": error,
            "text_starts_raw_pdf": 0,
        }
    result = extract_document_text(payload, url, primary_doc)
    return payload, result


def recent_block_to_rows(block: Dict, cik10: str) -> List[Dict]:
    if not block:
        return []
    accs = block.get("accessionNumber", [])
    rows = []
    for i in range(len(accs)):
        row = {k: (v[i] if isinstance(v, list) and i < len(v) else None) for k, v in block.items()}
        row["cik10"] = cik10
        rows.append(row)
    return rows


def collect_company_filings(
    cik10: str,
    user_agent: str,
    sleep: float,
) -> Tuple[pd.DataFrame, str]:
    url = f"https://data.sec.gov/submissions/CIK{cik10}.json"
    data, error = fetch_json(url, user_agent, sleep=sleep)
    if not data:
        return pd.DataFrame(), error or "no submissions metadata"

    rows = recent_block_to_rows(data.get("filings", {}).get("recent", {}), cik10)
    errors = []

    for filing_file in data.get("filings", {}).get("files", []):
        name = filing_file.get("name")
        if not name:
            continue
        old_url = f"https://data.sec.gov/submissions/{name}"
        old_data, old_error = fetch_json(old_url, user_agent, sleep=sleep)
        if old_data:
            rows.extend(recent_block_to_rows(old_data, cik10))
        elif old_error:
            errors.append(f"{name}: {old_error}")

    return pd.DataFrame(rows), "; ".join(errors)


def count_hits(text: str, patterns: Iterable[str]) -> int:
    if not text:
        return 0
    return sum(len(re.findall(pattern, text, flags=re.IGNORECASE)) for pattern in patterns)


def build_archive_url(cik10: str, accession: str, primary_doc: str) -> Optional[str]:
    if not accession or not primary_doc:
        return None
    cik_int = str(int(cik10))
    accession_nodash = str(accession).replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}/{primary_doc}"


def classify_text(text: str) -> Dict[str, int]:
    liq_hits = count_hits(text, LIQ_PATTERNS)
    equity_hits = count_hits(text, EQUITY_PATTERNS)
    annual_hits = count_hits(text, ANNUAL_REVIEW_PATTERNS)
    return {
        "liq_comment": int(liq_hits > 0),
        "equity_liq_comment": int(liq_hits > 0 and equity_hits > 0),
        "annual_related": int(annual_hits > 0),
        "n_liq_keyword_hits": liq_hits,
        "n_equity_keyword_hits": equity_hits,
        "n_annual_keyword_hits": annual_hits,
    }


def read_existing_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str)


def append_csv(path: Path, rows: List[Dict], fieldnames: List[str]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerows(rows)


def write_empty_outputs(filing_path: Path, firmyear_path: Path, log_path: Path) -> None:
    if not filing_path.exists():
        pd.DataFrame(columns=FILING_COLUMNS).to_csv(filing_path, index=False)
    if not firmyear_path.exists():
        pd.DataFrame(columns=FIRMYEAR_COLUMNS).to_csv(firmyear_path, index=False)
    if not log_path.exists():
        pd.DataFrame(columns=["cik10", "gvkey", "status", "n_metadata_rows", "n_comment_rows", "error"]).to_csv(
            log_path, index=False
        )


def rebuild_firmyear(filing_path: Path, firmyear_path: Path) -> None:
    filing_df = read_existing_csv(filing_path)
    if filing_df.empty:
        pd.DataFrame(columns=FIRMYEAR_COLUMNS).to_csv(firmyear_path, index=False)
        return

    for col in [
        "comment_year",
        "liq_comment",
        "equity_liq_comment",
        "annual_related",
        "text_length",
    ]:
        filing_df[col] = pd.to_numeric(filing_df[col], errors="coerce").fillna(0).astype(int)

    upload = filing_df[filing_df["form"].astype(str).str.upper() == "UPLOAD"].copy()
    if upload.empty:
        pd.DataFrame(columns=FIRMYEAR_COLUMNS).to_csv(firmyear_path, index=False)
        return

    fy = upload.groupby(["cik10", "comment_year"], as_index=False).agg(
        gvkey=("gvkey", "first"),
        n_upload=("accession", "count"),
        n_liq_comment=("liq_comment", "sum"),
        n_equity_liq_comment=("equity_liq_comment", "sum"),
        n_annual_related=("annual_related", "sum"),
        total_text_length=("text_length", "sum"),
    )
    fy["own_liq_comment"] = (fy["n_liq_comment"] > 0).astype(int)
    fy["own_equity_liq_comment"] = (fy["n_equity_liq_comment"] > 0).astype(int)
    fy["own_annual_related_comment"] = (fy["n_annual_related"] > 0).astype(int)
    fy = fy[FIRMYEAR_COLUMNS]
    fy.to_csv(firmyear_path, index=False)


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def progress_message(done: int, total: int, started_at: float, active_done: int) -> str:
    elapsed = time.time() - started_at
    pct = 100.0 * done / total if total else 100.0
    if done:
        eta = elapsed / done * (total - done)
        eta_text = format_duration(eta)
    else:
        eta_text = "unknown"
    return (
        f"Progress: {done:,}/{total:,} CIKs ({pct:.1f}%), "
        f"active_downloaded={active_done:,}, elapsed={format_duration(elapsed)}, ETA={eta_text}"
    )


def first_present(row: pd.Series, names: Iterable[str]) -> str:
    for name in names:
        if name in row.index and pd.notna(row.get(name)):
            value = str(row.get(name)).strip()
            if value and value.lower() != "nan":
                return value
    return ""


def extract_letter_row(
    filing: pd.Series,
    cik10: str,
    gvkey: str,
    args: argparse.Namespace,
    text_dir: Path,
    raw_dir: Path,
) -> Tuple[Optional[Dict[str, object]], str]:
    accession = first_present(filing, ["accessionNumber", "accession", "accession_number"])
    primary_doc = first_present(filing, ["primaryDocument", "primary_doc", "file_name", "filename"])
    url = first_present(filing, ["url", "filing_url", "document_url"])
    if not url:
        url = build_archive_url(cik10, accession, primary_doc) or ""
    if not url:
        return None, f"{accession}: missing archive url"

    if not primary_doc:
        primary_doc = Path(url).name

    safe_acc = re.sub(r"[^0-9A-Za-z]", "", accession)
    safe_doc = re.sub(r"[^0-9A-Za-z_.-]", "_", primary_doc)
    raw_path = raw_dir / f"{cik10}_{safe_acc}_{safe_doc}"
    text_path = text_dir / f"{cik10}_{safe_acc}_{safe_doc}.txt"

    extract_info: Dict[str, object]
    text = reusable_existing_text(text_path)
    if text is not None:
        extract_info = {
            "source_doc_type": source_doc_type(url, primary_doc, raw_path.read_bytes()[:16] if raw_path.exists() else b""),
            "extraction_method": "existing_text",
            "text_extraction_error": "",
            "text_starts_raw_pdf": text_starts_raw_pdf(text),
        }
    else:
        if raw_path.exists():
            payload = raw_path.read_bytes()
            extract_info = extract_document_text(payload, url, primary_doc)
        else:
            payload, extract_info = fetch_document_text(url, primary_doc, args.user_agent, sleep=args.sleep)
            if payload:
                raw_path.write_bytes(payload)
        text = str(extract_info.get("text", ""))
        text_path.write_text(text, encoding="utf-8", errors="ignore")

    text_error = str(extract_info.get("text_extraction_error", ""))
    cls = classify_text(text)
    filing_date = first_present(filing, ["filingDate", "filing_date_public", "filing_date"])
    comment_year = first_present(filing, ["filing_year", "comment_year"])
    if not comment_year and filing_date:
        dt = pd.to_datetime(filing_date, errors="coerce")
        comment_year = str(int(dt.year)) if pd.notna(dt) else ""

    out = {
        "gvkey": gvkey,
        "cik10": cik10,
        "form": first_present(filing, ["form", "form_type"]) or "UPLOAD",
        "accession": accession,
        "filing_date_public": filing_date,
        "comment_year": int(float(comment_year)) if comment_year else "",
        "reportDate": first_present(filing, ["reportDate", "report_date"]),
        "primary_doc": primary_doc,
        "url": url,
        "source_doc_type": extract_info.get("source_doc_type", ""),
        "extraction_method": extract_info.get("extraction_method", ""),
        "raw_file": str(raw_path),
        "text_file": str(text_path),
        "text_length": len(text),
        "text_extraction_error": text_error,
        "text_starts_raw_pdf": extract_info.get("text_starts_raw_pdf", 0),
        **cls,
    }
    return out, text_error


def recrawl_from_filing_csv(
    args: argparse.Namespace,
    text_dir: Path,
    raw_dir: Path,
    filing_path: Path,
    firmyear_path: Path,
    log_path: Path,
) -> None:
    old = pd.read_csv(args.filing_csv, dtype=str)
    if "cik10" not in old.columns:
        raise ValueError("--filing-csv must include cik10")
    old["cik10"] = old["cik10"].apply(pad_cik)
    if "gvkey" not in old.columns:
        old["gvkey"] = ""
    if "form" in old.columns:
        old = old[old["form"].astype(str).str.upper().eq("UPLOAD")].copy()
    year_col = "comment_year" if "comment_year" in old.columns else "filing_year" if "filing_year" in old.columns else ""
    if year_col:
        years = pd.to_numeric(old[year_col], errors="coerce")
        old = old[years.between(args.start_year, args.end_year)].copy()
    if args.limit is not None:
        old = old.head(args.limit).copy()

    done_ciks = set()
    if args.resume:
        log_df = read_existing_csv(log_path)
        if not log_df.empty and {"cik10", "status"}.issubset(log_df.columns):
            done_ciks = set(log_df.loc[log_df["status"].eq("ok"), "cik10"].astype(str))

    groups = list(old.groupby("cik10", sort=False))
    total = len(groups)
    started_at = time.time()
    active_done = 0
    print(progress_message(0, total, started_at, active_done), flush=True)
    for n, (cik10, grp) in enumerate(groups, start=1):
        gvkey = first_present(grp.iloc[0], ["gvkey"])
        if args.resume and cik10 in done_ciks:
            print(f"[{n}/{total}] CIK {cik10} skipped (already ok)", flush=True)
            continue
        print(f"[{n}/{total}] CIK {cik10} ({len(grp)} letters from filing CSV)", flush=True)
        rows = []
        errors = []
        for _, filing in grp.iterrows():
            row_out, err = extract_letter_row(filing, cik10, gvkey, args, text_dir, raw_dir)
            if row_out is not None:
                rows.append(row_out)
            if err:
                errors.append(err)
        append_csv(filing_path, rows, FILING_COLUMNS)
        append_csv(
            log_path,
            [{
                "cik10": cik10,
                "gvkey": gvkey,
                "status": "ok",
                "n_metadata_rows": "",
                "n_comment_rows": len(grp),
                "error": "; ".join(errors),
            }],
            ["cik10", "gvkey", "status", "n_metadata_rows", "n_comment_rows", "error"],
        )
        active_done += 1
        if args.progress_every > 0 and n % args.progress_every == 0:
            print(progress_message(n, total, started_at, active_done), flush=True)

    rebuild_firmyear(filing_path, firmyear_path)
    print(progress_message(total, total, started_at, active_done), flush=True)


def first_nonempty(values: pd.Series) -> str:
    for value in values:
        if value is None or pd.isna(value):
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def read_panel_for_ciks(path: Path, cik_cols: List[str]) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Panel not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".dta":
        if pyreadstat is None:
            raise ImportError("Reading .dta panels requires pyreadstat. Install requirements.txt.")
        _empty, meta = pyreadstat.read_dta(str(path), metadataonly=True)
        available = set(meta.column_names)
        usecols = [c for c in [*cik_cols, "gvkey", "tic", "conm", "fiscal_year", "fyear"] if c in available]
        if not usecols:
            raise ValueError(f"No requested CIK columns found in {path}: {cik_cols}")
        df, _meta = pyreadstat.read_dta(str(path), usecols=usecols)
    else:
        header = pd.read_csv(path, nrows=0)
        available = set(header.columns)
        usecols = [c for c in [*cik_cols, "gvkey", "tic", "conm", "fiscal_year", "fyear"] if c in available]
        if not usecols:
            raise ValueError(f"No requested CIK columns found in {path}: {cik_cols}")
        df = pd.read_csv(path, dtype=str, usecols=usecols)

    cik10 = pd.Series([""] * len(df), index=df.index, dtype=object)
    for col in cik_cols:
        if col not in df.columns:
            continue
        candidate = df[col].apply(pad_cik)
        missing = cik10.eq("")
        cik10.loc[missing] = candidate.loc[missing]
    df["cik10"] = cik10
    df = df[df["cik10"].str.len() == 10].copy()
    if df.empty:
        raise ValueError("No valid 10-digit CIKs found in panel.")

    agg_spec = {}
    for col in ["gvkey", "tic", "conm"]:
        if col in df.columns:
            agg_spec[col] = (col, first_nonempty)
    year_col = "fiscal_year" if "fiscal_year" in df.columns else "fyear" if "fyear" in df.columns else None
    if year_col:
        df[year_col] = pd.to_numeric(df[year_col], errors="coerce")
        agg_spec["min_fiscal_year"] = (year_col, "min")
        agg_spec["max_fiscal_year"] = (year_col, "max")
        agg_spec["n_panel_rows"] = (year_col, "size")
    else:
        agg_spec["n_panel_rows"] = ("cik10", "size")

    return df.groupby("cik10", as_index=False).agg(**agg_spec).sort_values("cik10")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", default="", help="Firm-year panel (.csv or .dta) with cik10, cik_string, or cik column")
    parser.add_argument("--filing-csv", default="", help="Existing filing-level CSV with SEC archive URLs to re-download/extract")
    parser.add_argument("--outdir", required=True, help="Output directory")
    parser.add_argument("--cik-cols", nargs="*", default=["cik10", "cik_string", "cik"], help="Candidate CIK columns, in priority order")
    parser.add_argument("--start-year", type=int, default=2003)
    parser.add_argument("--end-year", type=int, default=2022)
    parser.add_argument(
        "--user-agent",
        default="Your Name your.email@example.com",
        help="SEC-compliant User-Agent. Replace with your name, affiliation, and contact email.",
    )
    parser.add_argument("--sleep", type=float, default=0.20, help="Seconds between requests")
    parser.add_argument("--limit", type=int, default=None, help="Optional pilot limit on number of CIKs")
    parser.add_argument("--resume", action="store_true", help="Skip CIKs already marked ok in crawl_log.csv")
    parser.add_argument("--progress-every", type=int, default=25, help="Print ETA every N completed CIKs")
    args = parser.parse_args()

    outdir = Path(args.outdir)
    text_dir = outdir / "comment_texts"
    raw_dir = outdir / "raw_filings"
    filing_path = outdir / "sec_comment_letter_filing_level.csv"
    firmyear_path = outdir / "sec_comment_firmyear.csv"
    log_path = outdir / "crawl_log.csv"
    outdir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    write_empty_outputs(filing_path, firmyear_path, log_path)

    if args.filing_csv:
        recrawl_from_filing_csv(args, text_dir, raw_dir, filing_path, firmyear_path, log_path)
        print("Done.")
        print(f"Filing-level output: {filing_path}")
        print(f"Firm-year output:    {firmyear_path}")
        print(f"Crawl log:           {log_path}")
        return

    if not args.panel:
        raise ValueError("Provide --panel for CIK metadata crawl or --filing-csv for URL re-extraction.")

    sample = read_panel_for_ciks(Path(args.panel), args.cik_cols)
    sample.to_csv(outdir / "sample_cik.csv", index=False)
    if "gvkey" not in sample.columns:
        sample["gvkey"] = ""
    sample = sample[sample["cik10"].str.len() == 10].drop_duplicates("cik10").copy()
    if args.limit is not None:
        sample = sample.head(args.limit).copy()

    done_ciks = set()
    if args.resume:
        log_df = read_existing_csv(log_path)
        if not log_df.empty and {"cik10", "status"}.issubset(log_df.columns):
            done_ciks = set(log_df.loc[log_df["status"].eq("ok"), "cik10"].astype(str))

    started_at = time.time()
    active_done = 0
    total = len(sample)
    print(progress_message(0, total, started_at, active_done), flush=True)

    for n, row in sample.reset_index(drop=True).iterrows():
        cik10 = row["cik10"]
        gvkey = row.get("gvkey", "")
        done = n + 1
        if args.resume and cik10 in done_ciks:
            print(f"[{done}/{total}] CIK {cik10} skipped (already ok)", flush=True)
            if args.progress_every > 0 and done % args.progress_every == 0:
                print(progress_message(done, total, started_at, active_done), flush=True)
            continue

        print(f"[{done}/{total}] CIK {cik10}", flush=True)
        filings, metadata_error = collect_company_filings(cik10, args.user_agent, sleep=args.sleep)
        if filings.empty:
            append_csv(
                log_path,
                [{"cik10": cik10, "gvkey": gvkey, "status": "no_filings_metadata", "error": metadata_error}],
                ["cik10", "gvkey", "status", "n_metadata_rows", "n_comment_rows", "error"],
            )
            active_done += 1
            if args.progress_every > 0 and done % args.progress_every == 0:
                print(progress_message(done, total, started_at, active_done), flush=True)
            continue

        if "filingDate" not in filings.columns or "form" not in filings.columns:
            append_csv(
                log_path,
                [{"cik10": cik10, "gvkey": gvkey, "status": "metadata_missing_required_columns", "error": metadata_error}],
                ["cik10", "gvkey", "status", "n_metadata_rows", "n_comment_rows", "error"],
            )
            active_done += 1
            if args.progress_every > 0 and done % args.progress_every == 0:
                print(progress_message(done, total, started_at, active_done), flush=True)
            continue

        filings["filingDate_dt"] = pd.to_datetime(filings["filingDate"], errors="coerce")
        filings["filing_year"] = filings["filingDate_dt"].dt.year
        filings["form_upper"] = filings["form"].astype(str).str.upper()
        comments = filings[
            filings["form_upper"].eq("UPLOAD")
            & filings["filing_year"].between(args.start_year, args.end_year)
        ].copy()

        filing_rows = []
        letter_errors = []
        for _, filing in comments.iterrows():
            accession = str(filing.get("accessionNumber", ""))
            primary_doc = str(filing.get("primaryDocument", ""))
            url = build_archive_url(cik10, accession, primary_doc)
            if not url:
                letter_errors.append(f"{accession}: missing archive url")
                continue

            safe_acc = re.sub(r"[^0-9A-Za-z]", "", accession)
            safe_doc = re.sub(r"[^0-9A-Za-z_.-]", "_", primary_doc)
            raw_path = raw_dir / f"{cik10}_{safe_acc}_{safe_doc}"
            text_path = text_dir / f"{cik10}_{safe_acc}_{safe_doc}.txt"

            extract_info: Dict[str, object]
            text = reusable_existing_text(text_path)
            if text is not None:
                extract_info = {
                    "source_doc_type": source_doc_type(url, primary_doc, raw_path.read_bytes()[:16] if raw_path.exists() else b""),
                    "extraction_method": "existing_text",
                    "text_extraction_error": "",
                    "text_starts_raw_pdf": text_starts_raw_pdf(text),
                }
            else:
                if raw_path.exists():
                    payload = raw_path.read_bytes()
                    extract_info = extract_document_text(payload, url, primary_doc)
                else:
                    payload, extract_info = fetch_document_text(url, primary_doc, args.user_agent, sleep=args.sleep)
                    if payload:
                        raw_path.write_bytes(payload)
                text = str(extract_info.get("text", ""))
                text_error = str(extract_info.get("text_extraction_error", ""))
                if text_error:
                    letter_errors.append(f"{accession}: {text_error}")
                text_path.write_text(text, encoding="utf-8", errors="ignore")

            cls = classify_text(text)
            filing_rows.append(
                {
                    "gvkey": gvkey,
                    "cik10": cik10,
                    "form": filing.get("form", ""),
                    "accession": accession,
                    "filing_date_public": filing.get("filingDate", ""),
                    "comment_year": int(filing.get("filing_year")) if pd.notna(filing.get("filing_year")) else "",
                    "reportDate": filing.get("reportDate", ""),
                    "primary_doc": primary_doc,
                    "url": url,
                    "source_doc_type": extract_info.get("source_doc_type", ""),
                    "extraction_method": extract_info.get("extraction_method", ""),
                    "raw_file": str(raw_path),
                    "text_file": str(text_path),
                    "text_length": len(text),
                    "text_extraction_error": extract_info.get("text_extraction_error", ""),
                    "text_starts_raw_pdf": extract_info.get("text_starts_raw_pdf", 0),
                    **cls,
                }
            )

        append_csv(filing_path, filing_rows, FILING_COLUMNS)
        all_errors = "; ".join([e for e in [metadata_error, *letter_errors] if e])
        append_csv(
            log_path,
            [
                {
                    "cik10": cik10,
                    "gvkey": gvkey,
                    "status": "ok",
                    "n_metadata_rows": len(filings),
                    "n_comment_rows": len(comments),
                    "error": all_errors,
                }
            ],
            ["cik10", "gvkey", "status", "n_metadata_rows", "n_comment_rows", "error"],
        )
        active_done += 1
        if args.progress_every > 0 and done % args.progress_every == 0:
            print(progress_message(done, total, started_at, active_done), flush=True)

    rebuild_firmyear(filing_path, firmyear_path)
    print(progress_message(total, total, started_at, active_done), flush=True)
    print("Done.")
    print(f"Filing-level output: {filing_path}")
    print(f"Firm-year output:    {firmyear_path}")
    print(f"Crawl log:           {log_path}")


if __name__ == "__main__":
    main()
