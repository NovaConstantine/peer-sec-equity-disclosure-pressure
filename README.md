# Peer SEC Equity Disclosure Pressure

This repository builds SEC comment-letter variables from SEC EDGAR comment letters. The first core variable is **SEC Equity Disclosure Pressure**, a firm-year measure of the firm's own SEC comment exposure about equity financing access in liquidity or financing-constraint contexts. The second core variable is **Peer SEC Equity Disclosure Pressure**, the lagged leave-one-out peer average of that firm-year exposure.

The code is designed for researchers who want to reproduce the variable from public SEC EDGAR data and merge it into their own firm-year panel.

This is a `v0.1-pre` public draft. It is ready for code sharing and replication testing, but not yet a final archival release.

## What The Pipeline Does

The pipeline has four steps:

1. Provide a firm-year panel.
2. Download SEC-originated `UPLOAD` comment letters for the panel's unique CIKs and extract usable text from PDF, TXT, or HTML source documents.
3. Classify comment-letter text into equity-focused financing-constraint topics.
4. Merge the classified topics back to the panel, build firm-year SEC Equity Disclosure Pressure, and build lagged leave-one-out peer variables.

The main firm-year intermediate variable is:

```text
own_eq_any_minus_debt_fce_broad
```

This is SEC Equity Disclosure Pressure. It equals equity-FCE comment exposure net of debt-FCE comment exposure for the same firm-year.

The main peer variable is:

```text
peer_sec_equity_pressure_ff48
```

This is the prior-year leave-one-out FF48 peer average of `own_eq_any_minus_debt_fce_broad`.

## Directory Layout

```text
code/
  01_crawl_sec_upload_comments.py
  02_process_sec_comment_letters_for_fce_iv.py
  03_build_peer_sec_equity_disclosure_pressure.py

docs/
  TECHNICAL_PROCESS.md
  VARIABLE_DICTIONARY.md

examples/
  example_firm_year_panel.csv
  example_sec_comment_firmyear_fce_topic.csv

requirements.txt
.gitignore
LICENSE
RELEASE_NOTES.md
```

## Installation

Create an environment and install dependencies:

```bash
pip install -r requirements.txt
```

The crawler uses Python standard-library HTTP tools, not `requests`. PDF comment letters are extracted with `pdfminer.six`; table and Stata support use `pandas`, `numpy`, and `pyreadstat`.

## Input Panel

The pipeline starts from one firm-year panel:

```text
data/firm_year_panel.csv
```

Required columns:

```text
firm id column: gvkey, firm_id, or any stable firm identifier
CIK column: cik10, cik_string, or cik
year column: fyear, fiscal_year, or year
peer group column: ffi48, sic3, or another industry/group variable
```

The scripts can read `.csv` or `.dta` panels. The crawler automatically extracts unique CIKs from the panel. The peer-variable builder uses the same panel and appends the generated variables.
Rows without valid CIKs are retained in the final output panel. They do not download SEC letters, but they remain in the industry-year peer denominator when peer variables are constructed.

See `examples/example_firm_year_panel.csv` for a minimal example. The example uses real-style column names and sample CIKs, but the non-identifier values are placeholders.

## Quick Local Example

You can test the peer-variable builder without downloading SEC data by using the small example files:

```bash
python code/03_build_peer_sec_equity_disclosure_pressure.py \
  --panel examples/example_firm_year_panel.csv \
  --topic examples/example_sec_comment_firmyear_fce_topic.csv \
  --outdir output/example_peer_variables \
  --peer-groups ffi48 \
  --no-dta
```

This writes:

```text
output/example_peer_variables/peer_sec_equity_disclosure_pressure_panel.csv
```

## Step 1: Download SEC UPLOAD Comment Letters

Use your own SEC-compliant User-Agent. SEC requests that automated tools identify the user and provide contact information.

```bash
python code/01_crawl_sec_upload_comments.py \
  --panel data/firm_year_panel.csv \
  --outdir output \
  --start-year 2003 \
  --end-year 2022 \
  --user-agent "Your Name your.email@example.com" \
  --sleep 0.20 \
  --resume \
  --progress-every 25
```

Main outputs:

```text
output/sample_cik.csv
output/sec_comment_letter_filing_level.csv
output/sec_comment_firmyear.csv
output/raw_filings/
output/comment_texts/
output/crawl_log.csv
```

The crawler keeps SEC-originated `UPLOAD` letters. Company response letters (`CORRESP`) are not used for the main variable.

The crawler saves the raw SEC primary document under `output/raw_filings/` and the extracted plain text under `output/comment_texts/`. PDF letters are processed with `pdfminer.six`. The filing-level metadata includes `source_doc_type`, `extraction_method`, `raw_file`, `text_file`, `text_length`, `text_extraction_error`, and `text_starts_raw_pdf`. If extracted text still begins with `%PDF`, it is marked as failed rather than silently passed to the classifier.

### SEC Fair-Access Note

Respect SEC fair-access expectations when crawling EDGAR. Use a descriptive User-Agent, keep `--sleep` at a reasonable value, use `--resume` instead of restarting completed downloads, and avoid parallel crawls that could overload SEC servers.

## Step 2: Classify Comment-Letter Text

```bash
python code/02_process_sec_comment_letters_for_fce_iv.py \
  --letters-csv output/sec_comment_letter_filing_level.csv \
  --text-dir output/comment_texts \
  --outdir output/topic_classifier \
  --year-col comment_year \
  --progress-every 5000
```

Main outputs:

```text
output/topic_classifier/sec_comment_items_fce_topic_classified.csv
output/topic_classifier/sec_comment_letters_fce_topic_classified.csv
output/topic_classifier/sec_comment_firmyear_fce_topic.csv
```

The firm-year file is the key input for peer-variable construction. It contains the own-firm SEC Equity Disclosure Pressure variable:

```text
own_eq_any_minus_debt_fce_broad
```

## Step 3: Build Peer SEC Equity Disclosure Pressure

```bash
python code/03_build_peer_sec_equity_disclosure_pressure.py \
  --panel data/firm_year_panel.csv \
  --topic output/topic_classifier/sec_comment_firmyear_fce_topic.csv \
  --outdir output/peer_variables \
  --peer-groups ffi48
```

Main output:

```text
output/peer_variables/peer_sec_equity_disclosure_pressure_panel.csv
output/peer_variables/peer_sec_equity_disclosure_pressure_panel.dta
```

The output panel keeps the firm-year intermediate variable and appends the peer variable:

```text
own_eq_any_minus_debt_fce_broad
```

```text
peer_sec_equity_pressure_ff48
```

`own_eq_any_minus_debt_fce_broad` measures the firm's own SEC equity disclosure pressure in the current firm-year. `peer_sec_equity_pressure_ff48` measures prior-year peer pressure and is the variable intended for peer-based research designs.

## Notes For Public Replication

- Do not commit downloaded SEC text files or generated output tables to GitHub.
- Use `--resume` when crawling SEC data.
- Use a valid SEC User-Agent.
- Respect SEC fair-access expectations and avoid aggressive request rates.
- Confirm `text_starts_raw_pdf` is zero before classification.
- Validate the classifier on a random sample before using the variable in a paper.
- If your panel uses a different industry classification, pass the relevant column through `--peer-groups`.
