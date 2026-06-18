#!/usr/bin/env python3
"""
Download SEC-originated UPLOAD comment letters for a firm-year panel.

The script reads CIKs from a panel, queries the SEC submissions API, keeps
form type UPLOAD, downloads the filing document, and writes extracted text.
PDF letters are parsed with pdfminer.six; TXT/HTML letters are decoded and
HTML-stripped. Company response letters (CORRESP) are not used.
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
    import pyreadstat
except Exception:  # pragma: no cover
    pyreadstat = None

try:
    from pdfminer.high_level import extract_text as pdf_extract_text
except Exception:  # pragma: no cover
    pdf_extract_text = None


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
]

LOG_COLUMNS = ["cik10", "gvkey", "status", "n_metadata_rows", "n_upload_rows", "error"]


def clean_id(value: object, zfill: int | None = None) -> str:
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


def first_nonempty(values: Iterable[object]) -> str:
    for value in values:
        if value is None or pd.isna(value):
            continue
        text = str(value).strip()
        if text and text.lower() != "nan":
            return text
    return ""


def read_panel(path: Path, cik_cols: List[str]) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Panel not found: {path}")

    if path.suffix.lower() == ".dta":
        if pyreadstat is None:
            raise ImportError("Reading .dta files requires pyreadstat.")
        _empty, meta = pyreadstat.read_dta(str(path), metadataonly=True)
        available = set(meta.column_names)
        usecols = [c for c in [*cik_cols, "gvkey", "fyear", "fiscal_year", "tic", "conm"] if c in available]
        df, _meta = pyreadstat.read_dta(str(path), usecols=usecols)
    else:
        header = pd.read_csv(path, nrows=0)
        available = set(header.columns)
        usecols = [c for c in [*cik_cols, "gvkey", "fyear", "fiscal_year", "tic", "conm"] if c in available]
        df = pd.read_csv(path, dtype=str, usecols=usecols, low_memory=False)

    if not any(c in df.columns for c in cik_cols):
        raise ValueError(f"No CIK column found. Tried: {', '.join(cik_cols)}")

    cik10 = pd.Series([""] * len(df), index=df.index, dtype=object)
    for col in cik_cols:
        if col not in df.columns:
            continue
        candidate = df[col].apply(clean_cik)
        missing = cik10.eq("")
        cik10.loc[missing] = candidate.loc[missing]
    df["cik10"] = cik10
    df = df[df["cik10"].str.len().eq(10)].copy()
    if df.empty:
        raise ValueError("No valid 10-digit CIKs found.")

    year_col = "fyear" if "fyear" in df.columns else "fiscal_year" if "fiscal_year" in df.columns else None
    agg = {}
    if "gvkey" in df.columns:
        agg["gvkey"] = ("gvkey", first_nonempty)
    for col in ["tic", "conm"]:
        if col in df.columns:
            agg[col] = (col, first_nonempty)
    if year_col:
        df[year_col] = pd.to_numeric(df[year_col], errors="coerce")
        agg["min_fiscal_year"] = (year_col, "min")
        agg["max_fiscal_year"] = (year_col, "max")
    agg["n_panel_rows"] = ("cik10", "size")
    return df.groupby("cik10", as_index=False).agg(**agg).sort_values("cik10")


def request_bytes(url: str, user_agent: str, sleep: float, max_retries: int = 3) -> Tuple[bytes, str]:
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


def fetch_json(url: str, user_agent: str, sleep: float) -> Tuple[Optional[Dict], str]:
    payload, error = request_bytes(url, user_agent, sleep=sleep)
    if not payload:
        return None, error
    try:
        return json.loads(payload.decode("utf-8")), ""
    except json.JSONDecodeError as exc:
        return None, f"JSON decode error: {exc}"


def block_to_rows(block: Dict, cik10: str) -> List[Dict]:
    accs = block.get("accessionNumber", []) if block else []
    rows = []
    for i in range(len(accs)):
        row = {k: (v[i] if isinstance(v, list) and i < len(v) else None) for k, v in block.items()}
        row["cik10"] = cik10
        rows.append(row)
    return rows


def collect_company_filings(cik10: str, user_agent: str, sleep: float) -> Tuple[pd.DataFrame, str]:
    url = f"https://data.sec.gov/submissions/CIK{cik10}.json"
    data, error = fetch_json(url, user_agent, sleep=sleep)
    if not data:
        return pd.DataFrame(), error or "no submissions metadata"

    rows = block_to_rows(data.get("filings", {}).get("recent", {}), cik10)
    errors = []
    for item in data.get("filings", {}).get("files", []):
        name = item.get("name")
        if not name:
            continue
        old_data, old_error = fetch_json(f"https://data.sec.gov/submissions/{name}", user_agent, sleep=sleep)
        if old_data:
            rows.extend(block_to_rows(old_data, cik10))
        elif old_error:
            errors.append(f"{name}: {old_error}")
    return pd.DataFrame(rows), "; ".join(errors)


def build_archive_url(cik10: str, accession: str, primary_doc: str) -> str:
    if not accession or not primary_doc:
        return ""
    accession_nodash = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik10)}/{accession_nodash}/{primary_doc}"


def strip_html(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw)
    raw = re.sub(r"(?is)<br\s*/?>", " ", raw)
    raw = re.sub(r"(?is)</p\s*>", " ", raw)
    raw = re.sub(r"(?is)<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    return re.sub(r"\s+", " ", raw).strip()


def decode_text(payload: bytes) -> str:
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


def is_raw_pdf_text(text: str) -> bool:
    return (text or "").lstrip().startswith("%PDF")


def reusable_text(path: Path) -> str | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")
    if not text.strip() or is_raw_pdf_text(text):
        return None
    return text


def extract_document_text(payload: bytes, url: str, primary_doc: str) -> Dict[str, object]:
    doc_type = source_doc_type(url, primary_doc, payload)
    text = ""
    method = ""
    error = ""

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
        text = decode_text(payload)
        if doc_type == "html":
            text = strip_html(text)

    text = re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()
    raw_pdf = int(is_raw_pdf_text(text))
    if raw_pdf:
        text = ""
        error = "; ".join([x for x in [error, "extracted text starts with raw PDF marker"] if x])
    if doc_type == "pdf" and not text:
        error = "; ".join([x for x in [error, "empty PDF text extraction"] if x])

    return {
        "text": text,
        "source_doc_type": doc_type,
        "extraction_method": method,
        "text_extraction_error": error,
        "text_starts_raw_pdf": raw_pdf,
    }


def append_csv(path: Path, rows: List[Dict], columns: List[str]) -> None:
    if not rows:
        return
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerows(rows)


def read_existing_log(path: Path) -> set[str]:
    if not path.exists() or path.stat().st_size == 0:
        return set()
    log = pd.read_csv(path, dtype=str)
    if {"cik10", "status"}.issubset(log.columns):
        return set(log.loc[log["status"].eq("ok"), "cik10"].astype(str))
    return set()


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def print_progress(done: int, total: int, started_at: float) -> None:
    elapsed = time.time() - started_at
    eta = elapsed / done * (total - done) if done else 0.0
    pct = 100 * done / total if total else 100
    print(
        f"Progress: {done:,}/{total:,} CIKs ({pct:.1f}%), "
        f"elapsed={format_duration(elapsed)}, ETA={format_duration(eta)}",
        flush=True,
    )


def download_uploads_for_cik(row: pd.Series, args: argparse.Namespace, text_dir: Path, raw_dir: Path) -> Tuple[List[Dict], Dict]:
    cik10 = str(row["cik10"])
    gvkey = clean_id(row.get("gvkey", ""), zfill=6)
    filings, meta_error = collect_company_filings(cik10, args.user_agent, args.sleep)
    if filings.empty:
        return [], {
            "cik10": cik10,
            "gvkey": gvkey,
            "status": "no_filings_metadata",
            "n_metadata_rows": 0,
            "n_upload_rows": 0,
            "error": meta_error,
        }

    if "filingDate" not in filings.columns or "form" not in filings.columns:
        return [], {
            "cik10": cik10,
            "gvkey": gvkey,
            "status": "metadata_missing_columns",
            "n_metadata_rows": len(filings),
            "n_upload_rows": 0,
            "error": meta_error,
        }

    filings["filingDate_dt"] = pd.to_datetime(filings["filingDate"], errors="coerce")
    filings["filing_year"] = filings["filingDate_dt"].dt.year
    filings["form_upper"] = filings["form"].astype(str).str.upper()
    uploads = filings[
        filings["form_upper"].eq("UPLOAD")
        & filings["filing_year"].between(args.start_year, args.end_year)
    ].copy()

    out_rows: List[Dict] = []
    errors = [meta_error] if meta_error else []
    for filing in uploads.itertuples(index=False):
        accession = str(getattr(filing, "accessionNumber", "") or "")
        primary_doc = str(getattr(filing, "primaryDocument", "") or "")
        url = build_archive_url(cik10, accession, primary_doc)
        if not url:
            errors.append(f"{accession}: missing archive URL")
            continue

        safe_acc = re.sub(r"[^0-9A-Za-z]", "", accession)
        safe_doc = re.sub(r"[^0-9A-Za-z_.-]", "_", primary_doc)
        raw_path = raw_dir / f"{cik10}_{safe_acc}_{safe_doc}"
        text_path = text_dir / f"{cik10}_{safe_acc}_{safe_doc}.txt"

        text = reusable_text(text_path)
        if text is not None:
            extract = {
                "source_doc_type": source_doc_type(url, primary_doc, raw_path.read_bytes()[:16] if raw_path.exists() else b""),
                "extraction_method": "existing_text",
                "text_extraction_error": "",
                "text_starts_raw_pdf": 0,
            }
        else:
            if raw_path.exists():
                payload = raw_path.read_bytes()
            else:
                payload, request_error = request_bytes(url, args.user_agent, args.sleep)
                if request_error:
                    errors.append(f"{accession}: {request_error}")
                if payload:
                    raw_path.write_bytes(payload)
            extract = extract_document_text(payload, url, primary_doc) if payload else {
                "text": "",
                "source_doc_type": source_doc_type(url, primary_doc, b""),
                "extraction_method": "",
                "text_extraction_error": "empty download",
                "text_starts_raw_pdf": 0,
            }
            text = str(extract.get("text", ""))
            if extract.get("text_extraction_error"):
                errors.append(f"{accession}: {extract.get('text_extraction_error')}")
            text_path.write_text(text, encoding="utf-8", errors="ignore")

        filing_date = str(getattr(filing, "filingDate", "") or "")
        filing_year = getattr(filing, "filing_year", "")
        out_rows.append(
            {
                "gvkey": gvkey,
                "cik10": cik10,
                "form": str(getattr(filing, "form", "") or ""),
                "accession": accession,
                "filing_date_public": filing_date,
                "comment_year": int(filing_year) if pd.notna(filing_year) else "",
                "reportDate": str(getattr(filing, "reportDate", "") or ""),
                "primary_doc": primary_doc,
                "url": url,
                "source_doc_type": extract.get("source_doc_type", ""),
                "extraction_method": extract.get("extraction_method", ""),
                "raw_file": str(raw_path),
                "text_file": str(text_path),
                "text_length": len(text or ""),
                "text_extraction_error": extract.get("text_extraction_error", ""),
                "text_starts_raw_pdf": extract.get("text_starts_raw_pdf", 0),
            }
        )

    log = {
        "cik10": cik10,
        "gvkey": gvkey,
        "status": "ok",
        "n_metadata_rows": len(filings),
        "n_upload_rows": len(uploads),
        "error": "; ".join([e for e in errors if e]),
    }
    return out_rows, log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", type=Path, required=True, help="Firm-year panel with CIKs (.csv or .dta)")
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--cik-cols", nargs="*", default=["cik10", "cik_string", "cik"])
    parser.add_argument("--start-year", type=int, default=2003)
    parser.add_argument("--end-year", type=int, default=2022)
    parser.add_argument("--user-agent", required=True, help="SEC-compliant User-Agent with name, affiliation, and email")
    parser.add_argument("--sleep", type=float, default=0.20)
    parser.add_argument("--limit", type=int, default=None, help="Optional pilot limit on number of CIKs")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--progress-every", type=int, default=25)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)
    text_dir = args.outdir / "comment_texts"
    raw_dir = args.outdir / "raw_filings"
    text_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    filing_path = args.outdir / "sec_comment_letter_filing_level.csv"
    log_path = args.outdir / "crawl_log.csv"
    if not filing_path.exists():
        pd.DataFrame(columns=FILING_COLUMNS).to_csv(filing_path, index=False)
    if not log_path.exists():
        pd.DataFrame(columns=LOG_COLUMNS).to_csv(log_path, index=False)

    sample = read_panel(args.panel, args.cik_cols)
    sample_path = args.outdir / "sample_cik.csv"
    sample.to_csv(sample_path, index=False)
    if args.limit is not None:
        sample = sample.head(args.limit).copy()

    done_ciks = read_existing_log(log_path) if args.resume else set()
    started = time.time()
    total = len(sample)
    print_progress(0, total, started)

    for pos, row in enumerate(sample.itertuples(index=False), start=1):
        cik10 = str(getattr(row, "cik10"))
        if args.resume and cik10 in done_ciks:
            print(f"[{pos}/{total}] CIK {cik10} skipped", flush=True)
            continue
        print(f"[{pos}/{total}] CIK {cik10}", flush=True)
        rows, log = download_uploads_for_cik(pd.Series(row._asdict()), args, text_dir, raw_dir)
        append_csv(filing_path, rows, FILING_COLUMNS)
        append_csv(log_path, [log], LOG_COLUMNS)
        if args.progress_every and pos % args.progress_every == 0:
            print_progress(pos, total, started)

    print_progress(total, total, started)
    print(f"Sample CIKs: {sample_path}")
    print(f"Filing-level metadata: {filing_path}")
    print(f"Text directory: {text_dir}")
    print(f"Crawl log: {log_path}")


if __name__ == "__main__":
    main()
