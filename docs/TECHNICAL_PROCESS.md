# Technical Process

This document describes the clean workflow used to construct the main peer SEC equity disclosure pressure variable.

## 1. SEC Comment Letter Collection

The crawler reads unique CIKs from a firm-year panel and queries the SEC submissions API:

```text
https://data.sec.gov/submissions/CIK##########.json
```

It keeps SEC-originated `UPLOAD` letters and excludes company response letters (`CORRESP`). For each `UPLOAD` filing, the crawler downloads the filing document from EDGAR archives.

PDF source documents are extracted with `pdfminer.six`. Text or HTML source documents are decoded and cleaned. The crawler saves both raw source files and extracted text files so PDF extraction can be audited.

## 2. Comment Item Classification

The classification step converts SEC comment-letter text into the two letter flags used by the IV formula:

```text
num_any_CFULLX
den_any_CFULLX_SRCFUNDS
```

The classifier splits each letter into comment items and applies `dictionary/peer_sec_equity_disclosure_dictionary.csv`. Each dictionary row is a regex term. Four binary dictionary columns determine how a term is used:

| Symbol | Dictionary column | Meaning |
| --- | --- | --- |
| `E_m` | `equity_financing_access_signal` | Item `m` contains equity-financing or equity-market-access language |
| `C_m` | `financing_disclosure_context_signal` | Item `m` contains financing-disclosure context language |
| `G_m` | `general_financing_disclosure_scope` | Item `m` contains other external-financing language |
| `X_m` | `nonfinancing_compensation_accounting_exclusion` | Item `m` uses equity language only in compensation, accounting, or valuation contexts |

The item-level rules are:

- A clean equity item hits `equity_financing_access_signal` and does not hit `nonfinancing_compensation_accounting_exclusion`.
- An SEC equity-financing item is a clean equity item that also hits `financing_disclosure_context_signal`.
- An SEC external-financing item either is a clean equity item or hits `general_financing_disclosure_scope`.

The letter-level rules are:

- `num_any_CFULLX` equals one if any item in the letter is an SEC equity-financing item.
- `den_any_CFULLX_SRCFUNDS` equals one if any item in the letter is an SEC external-financing item.

The SEC external-financing comment flag is not all SEC review activity. It includes
SEC equity-financing comments plus other comments
about financing sources and capital access. Regulation S-K Item 303 requires
MD&A disclosure about liquidity and capital resources, including material cash
requirements and sources of liquidity. Hoberg and Maksimovic (2015) and Linn
and Weagley (2024) motivate separating equity-related financing frictions from
other financing frictions. Specific instrument terms, such as credit facilities,
notes payable, and borrowings, reflect the way SEC comments discuss external
financing channels. Term-level support is documented in the dictionary reference
table.

The equity-financing dictionary starts from the Hoberg and Maksimovic (2015)
equity-focused financing concept. Their original setting is firms' own 10-K
constraint disclosure. SEC comment letters use different wording because they
are staff requests about filings, offerings, liquidity, and sources of funds.
The dictionary therefore adapts the HM concept to the SEC comment-letter setting
by retaining HM-style equity financing phrases when applicable and adding
comment-letter terms for equity securities, common-stock offerings or issuance,
private placements, access to equity markets, and related financing-disclosure
contexts. The exact term list and reference support are in:

```text
dictionary/peer_sec_equity_disclosure_dictionary.csv
dictionary/peer_sec_equity_disclosure_dictionary_reference.csv
```

For a compact summary of which terms enter `E_m`, `C_m`, `G_m`, and `X_m`, see `docs/VARIABLE_DICTIONARY.md`. The two letter-level indicators above are the only classification inputs needed to build the final peer variables.

## 3. Peer Timing

For each focal firm-year observation, peer comments are counted using the focal firm's `datadate` window:

```math
\mathrm{prev\_datadate}_{i,t}<\tau_{j,\ell}\le \mathrm{datadate}_{i,t},
```

where $\tau_{j,\ell}$ is the SEC public release date of comment letter $\ell$ for peer firm $j$.

## 4. Peer Group

Peers are firms in the same FF48 industry group. Peer events are assigned using the focal observation's prior fiscal year:

```text
base_fyear = focal fyear - 1
base_ffi48 = focal ffi48
```

The focal firm itself is excluded from the peer count.

## 5. Output Variables

The main variable is a peer-firm ratio. This aggregation follows the peer
spillover logic: the relevant exposure is whether peer firms receive SEC
comments on equity-financing disclosure, not the number of split
items in a letter.

```math
\text{Peer SEC Equity Disclosure Pressure}_{i,t}
=
\frac{N^{\mathrm{Equity}}_{i,t}}{N^{\mathrm{External}}_{i,t}} .
```

Replication output column:

```text
FF48_C_SRCFUNDS_firmshare
```

$N^{\mathrm{Equity}}_{i,t}$ is the number of distinct same-FF48 peer firms with `num_any_CFULLX = 1`, and $N^{\mathrm{External}}_{i,t}$ is the number of distinct same-FF48 peer firms with `den_any_CFULLX_SRCFUNDS = 1`, measured in the focal firm's `datadate` window.

The robustness variable is a peer-letter ratio:

```text
FF48_CFULLX_SRCFUNDS_lettershare
  =
peer letters with num_any_CFULLX = 1
/
peer letters with den_any_CFULLX_SRCFUNDS = 1
```

The builder also writes numerator and denominator counts for audit purposes.

## 6. Reproducibility Checks

Recommended checks before using the variables:

```text
1. Confirm PDF extraction did not pass raw %PDF bytes into classification.
2. Check the number of positive equity-financing and external-financing letters.
3. Inspect positive item examples manually.
4. Confirm the distribution of FF48_C_SRCFUNDS_firmshare.
5. Confirm that the final regression sample begins in fiscal year 2006 if following Brown-style public comment-letter availability.
```
