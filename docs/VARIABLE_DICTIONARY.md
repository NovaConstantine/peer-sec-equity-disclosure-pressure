# Variable Dictionary

## Paper Variable and Output Columns

The paper/table variable is:

```text
Peer SEC Equity Disclosure Pressure
```

The replication output column for this variable is:

```text
FF48_C_SRCFUNDS_firmshare
```

It is the distinct-peer-firm ratio:

```math
\text{Peer SEC Equity Disclosure Pressure}_{i,t}
=
\frac{N^{\mathrm{Equity}}_{i,t}}{N^{\mathrm{External}}_{i,t}} .
```

$N^{\mathrm{Equity}}_{i,t}$ is the number of distinct same-FF48 peer firms with SEC equity-financing comments, and $N^{\mathrm{External}}_{i,t}$ is the number of distinct same-FF48 peer firms with SEC external-financing comments.

This is the preferred variable for empirical tests. The ratio scales equity-financing SEC attention by external-financing disclosure comments, so the variable is not simply a count of SEC reviews or a proxy for capital-market activity in an industry.

The robustness output column is:

```text
FF48_CFULLX_SRCFUNDS_lettershare
```

It uses peer-comment-letter counts with the same comment classifications:

```text
same-FF48 peer letters with SEC equity-financing comments
/
same-FF48 peer letters with SEC external-financing comments
```

The output also includes an alias:

```text
FF48_CFULLX_SRCFUNDS_firmshare
```

Exact alias for:

```text
FF48_C_SRCFUNDS_firmshare
```

The alias is kept for traceability to the construction code.

## Classification Logic

The classifier applies `dictionary/peer_sec_equity_disclosure_dictionary.csv` to SEC comment items. Each row is a regex term. Four dictionary columns determine the item-level classification:

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

The code writes these letter-level inputs as:

```text
num_any_CFULLX
```

Equals one if the SEC letter contains at least one SEC equity-financing item.

```text
den_any_CFULLX_SRCFUNDS
```

Equals one if the SEC letter contains at least one SEC external-financing item.

## Dictionary Roles

The final dictionary is stored in:

```text
dictionary/peer_sec_equity_disclosure_dictionary.csv
```

Each row is a regex term. Roles are binary columns:

```text
equity_financing_access_signal
financing_disclosure_context_signal
general_financing_disclosure_scope
nonfinancing_compensation_accounting_exclusion
```

### Dictionary Columns Used in the Formula

| Formula role | Dictionary column | Source logic | Representative terms from the dictionary |
| --- | --- | --- | --- |
| `E_m` | `equity_financing_access_signal` | 25 terms are HM equity-focused financing phrases; 40 terms are SEC-language additions for equity securities, offerings, and equity-market access | `equity securities`; `registered offering of common stock`; `public offering of common stock`; `access equity markets` |
| `C_m` | `financing_disclosure_context_signal` | SEC MD&A liquidity/capital-resources context and SEC comment-letter financing-stress language | `capital resources`; `liquidity`; `cash requirements`; `unable to obtain financing`; `going concern` |
| `G_m` | `general_financing_disclosure_scope` | Source-of-funds, capital-access, debt/credit-financing, equity-financing, and unable-to-finance language | `sources of funds`; `external financing`; `credit facility`; `notes payable`; `borrowings` |
| `X_m` | `nonfinancing_compensation_accounting_exclusion` | Compensation, accounting, and valuation contexts where equity words do not refer to external equity financing | `stock-based compensation`; `option awards`; `ASC 718`; `fair value`; `warrant accounting` |

Use the CSV files for the complete dictionary:

```text
dictionary/peer_sec_equity_disclosure_dictionary.csv
dictionary/peer_sec_equity_disclosure_dictionary_reference.csv
```

`equity_financing_access_signal` contains equity financing, equity securities, common-stock issuance, offerings, private placements, and HM equity-focused phrases retained for traceability.

The equity-financing terms are anchored in the Hoberg and Maksimovic (2015)
equity-focused financing concept. Because HM classify firms' own 10-K text, the
dictionary adapts that concept to SEC comment letters by adding staff-comment
language about offerings, securities, common-stock issuance or sales, private
placements, equity-market access, and related source-of-funds disclosure. The
full row-level source support is in
`dictionary/peer_sec_equity_disclosure_dictionary_reference.csv`.

`financing_disclosure_context_signal` contains financing-disclosure context terms such as MD&A, liquidity, capital resources, source-of-funds, known uncertainty, going concern, and unable-to-finance language. These terms are used to require that equity language appears in a financing-disclosure setting rather than as an isolated stock or equity mention.

`general_financing_disclosure_scope` contains the comparison set for SEC external-financing disclosure review. It includes SEC equity-financing comments plus other comments about financing sources and capital access. Regulation S-K Item 303 requires MD&A disclosure about liquidity and capital resources, including material cash requirements and sources of liquidity. Hoberg and Maksimovic (2015) and Linn and Weagley (2024) motivate separating equity-related financing frictions from other financing frictions. The role includes source-of-funds and liquidity terms, external financing and capital-access terms, and debt or credit financing terms. Specific instrument terms, such as credit facilities, notes payable, and borrowings, are included because SEC comments often discuss external financing through these channels; row-level support is provided in the dictionary reference table.

`nonfinancing_compensation_accounting_exclusion` contains compensation, accounting, and valuation terms used to remove equity mentions that are not about external equity financing.

`term_family` groups terms by economic content:

```text
HM equity-focused financing phrase
Equity securities and offerings
Equity financing and market access
MD&A liquidity and source-of-funds context
Financial constraint and going-concern context
Known trends and uncertainties context
Source-of-funds and liquidity
External financing and capital access
Debt and credit financing
Non-financing compensation/accounting/valuation
```

## Reference Table

The dictionary reference table is stored in:

```text
dictionary/peer_sec_equity_disclosure_dictionary_reference.csv
```

It separates:

```text
exact_reference_*
rationale_reference_*
```

`exact_reference_*` is used only when the exact term or phrase appears in the cited source. When the exact wording is not in a rule or paper dictionary, the table uses an SEC comment-letter excerpt as exact usage support.
