# Peer SEC Equity Disclosure Pressure

This repository constructs the paper variable **Peer SEC Equity Disclosure Pressure** from public SEC EDGAR `UPLOAD` comment letters. The workflow is intentionally narrow: it includes only the code and dictionary needed to build the main IV and one robustness variable. It does not include candidate searches, regression code, placebo tests, or paper-specific table generation.

## Start Here: IV Calculation

| Paper/table name | Replication output column | Definition |
| --- | --- | --- |
| Peer SEC Equity Disclosure Pressure | `FF48_C_SRCFUNDS_firmshare` | Distinct-peer-firm ratio of SEC equity-financing comments to SEC external-financing comments |
| Robustness variable | `FF48_CFULLX_SRCFUNDS_lettershare` | Peer-comment-letter ratio using the same comment classifications |

For focal firm `i` in fiscal year `t`, the main variable is:

```math
\text{Peer SEC Equity Disclosure Pressure}_{i,t}
=
\frac{N^{\mathrm{Equity}}_{i,t}}{N^{\mathrm{External}}_{i,t}} .
```

Let $\tau_{j,\ell}$ be the SEC public release date of comment letter $\ell$ for peer firm $j$. The two counts are defined as follows:

- `N^{Equity}` counts distinct same-FF48 peer firms, excluding the focal firm, with at least one SEC equity-financing comment in the focal firm's `datadate` window.
- `N^{External}` counts distinct same-FF48 peer firms, excluding the focal firm, with at least one SEC external-financing comment in the focal firm's `datadate` window.

The `datadate` window is:

```math
\mathrm{prev\_datadate}_{i,t}<\tau_{j,\ell}\le \mathrm{datadate}_{i,t}.
```

Peer membership is measured in the focal observation's prior fiscal year and FF48 industry group. If there are no same-FF48 peer firms with SEC external-financing comments in the datadate window, the code assigns the ratio to zero.

Scaling by peer external-financing comments reduces the influence of overall SEC review intensity and general external-financing activity, so the measure captures the equity orientation of peer SEC financing-disclosure attention.

## Comment Classification Formula

The classifier applies `dictionary/peer_sec_equity_disclosure_dictionary.csv` to each SEC comment item. Each dictionary row is a regex term. The four binary role columns determine how the term enters the classification:

| Symbol | Dictionary column | Meaning | Examples |
| --- | --- | --- | --- |
| `E_m` | `equity_financing_access_signal` | Item `m` contains equity-financing or equity-market-access language | `equity securities`; `registered offering of common stock`; `public offering of common stock`; `access equity markets` |
| `C_m` | `financing_disclosure_context_signal` | Item `m` contains a financing-disclosure context term | `capital resources`; `liquidity`; `cash requirements`; `unable to obtain financing`; `going concern` |
| `G_m` | `general_financing_disclosure_scope` | Item `m` contains other external-financing language | `sources of funds`; `external financing`; `credit facility`; `notes payable`; `borrowings` |
| `X_m` | `nonfinancing_compensation_accounting_exclusion` | Item `m` uses equity language only in compensation, accounting, or valuation contexts | `stock-based compensation`; `option awards`; `ASC 718`; `fair value`; `warrant accounting` |

The item-level rules are:

- A clean equity item hits `equity_financing_access_signal` and does not hit `nonfinancing_compensation_accounting_exclusion`.
- An SEC equity-financing item is a clean equity item that also hits `financing_disclosure_context_signal`.
- An SEC external-financing item either is a clean equity item or hits `general_financing_disclosure_scope`.

The letter-level rules are:

- A letter is an SEC equity-financing letter if any item in the letter is an SEC equity-financing item.
- A letter is an SEC external-financing letter if any item in the letter is an SEC external-financing item.

The peer-level ratio above counts distinct peer firms with `EquityFinancingLetter = 1` in the numerator and distinct peer firms with `ExternalFinancingLetter = 1` in the denominator. The robustness variable `FF48_CFULLX_SRCFUNDS_lettershare` uses the same letter flags but counts peer letters instead of distinct peer firms.

## Dictionary Files

The full dictionary is in:

```text
dictionary/peer_sec_equity_disclosure_dictionary.csv
```

Term-level references and examples are in:

```text
dictionary/peer_sec_equity_disclosure_dictionary_reference.csv
```

In the current dictionary, the equity-financing role contains 25 HM-sourced terms and 40 SEC-language appended terms. The external-financing role contains 25 terms covering source-of-funds, capital-access, debt/credit-financing, and unable-to-finance language.

## Repository Structure

```text
code/
  01_crawl_sec_upload_comments.py
  02_classify_sec_equity_disclosure_comments.py
  03_build_peer_sec_equity_disclosure_pressure.py

dictionary/
  peer_sec_equity_disclosure_dictionary.csv
  peer_sec_equity_disclosure_dictionary_reference.csv

docs/
  TECHNICAL_PROCESS.md
  VARIABLE_DICTIONARY.md

examples/
  example_firm_year_panel.csv
  example_sec_comment_letter_flags.csv
```

## Installation

```bash
pip install -r requirements.txt
```

`pdfminer.six` is required to extract text from PDF comment letters. `pyreadstat` is required only for Stata `.dta` input/output.

## Input Panel

Provide a firm-year panel in CSV or Stata `.dta` format. Required columns:

```text
gvkey or another stable firm identifier
fyear, fiscal_year, or year
datadate
ffi48
cik10, cik_string, or cik
```

The crawler extracts unique CIKs from this panel. The peer-variable builder uses `gvkey`, `fyear`, `datadate`, and `ffi48`.

## Step 1: Download SEC UPLOAD Comment Letters

Use a descriptive SEC User-Agent with your name, affiliation, and email.

```bash
python code/01_crawl_sec_upload_comments.py \
  --panel data/firm_year_panel.csv \
  --outdir output/sec_comments \
  --start-year 2003 \
  --end-year 2022 \
  --user-agent "Your Name Your Institution your.email@example.com" \
  --sleep 0.20 \
  --resume \
  --progress-every 25
```

Main outputs:

```text
output/sec_comments/sample_cik.csv
output/sec_comments/sec_comment_letter_filing_level.csv
output/sec_comments/comment_texts/
output/sec_comments/raw_filings/
output/sec_comments/crawl_log.csv
```

Only SEC-originated `UPLOAD` letters are used. Company response letters (`CORRESP`) are not used.

## Step 2: Classify Comment Letters

```bash
python code/02_classify_sec_equity_disclosure_comments.py \
  --letters-csv output/sec_comments/sec_comment_letter_filing_level.csv \
  --text-dir output/sec_comments/comment_texts \
  --dictionary dictionary/peer_sec_equity_disclosure_dictionary.csv \
  --outdir output/equity_disclosure_letter_flags \
  --progress-every 5000
```

Main outputs:

```text
output/equity_disclosure_letter_flags/sec_comment_letter_equity_disclosure_flags.csv
output/equity_disclosure_letter_flags/sec_comment_item_equity_disclosure_flags.csv
output/equity_disclosure_letter_flags/dictionary_role_counts.csv
```

The script applies the item-level and letter-level formulas shown in **Comment Classification Formula** above. The complete term list is in `dictionary/peer_sec_equity_disclosure_dictionary.csv`, and term-level support is in `dictionary/peer_sec_equity_disclosure_dictionary_reference.csv`.

## Step 3: Build Peer Variables

```bash
python code/03_build_peer_sec_equity_disclosure_pressure.py \
  --panel data/firm_year_panel.csv \
  --letter-flags output/equity_disclosure_letter_flags/sec_comment_letter_equity_disclosure_flags.csv \
  --outdir output/peer_variables
```

Main outputs:

```text
output/peer_variables/peer_sec_equity_disclosure_pressure_panel.csv
output/peer_variables/peer_sec_equity_disclosure_pressure_panel.dta
output/peer_variables/peer_sec_equity_disclosure_pressure_distribution.csv
```

The output panel appends:

```text
FF48_C_SRCFUNDS_firmshare
FF48_CFULLX_SRCFUNDS_firmshare
FF48_CFULLX_SRCFUNDS_lettershare
peer_CFULLX_num_firms
peer_CFULLX_num_letters
peer_SRCFUNDS_denominator_firms
peer_SRCFUNDS_denominator_letters
```

`FF48_CFULLX_SRCFUNDS_firmshare` is included as an exact alias for `FF48_C_SRCFUNDS_firmshare`.

## Quick Example Without SEC Download

```bash
python code/03_build_peer_sec_equity_disclosure_pressure.py \
  --panel examples/example_firm_year_panel.csv \
  --letter-flags examples/example_sec_comment_letter_flags.csv \
  --outdir output/example_peer_variables \
  --no-dta
```
