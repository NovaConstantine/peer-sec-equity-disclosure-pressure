# Technical Process

This document describes how the code constructs two related variables: **SEC Equity Disclosure Pressure** at the firm-year level, and **Peer SEC Equity Disclosure Pressure** as its lagged leave-one-out peer average.

## 1. CIK Universe

The starting point is a user-supplied firm-year panel:

```text
data/firm_year_panel.csv
```

Minimum required information:

```text
stable firm identifier
CIK
fiscal year
peer group / industry
```

The default expected column names are:

```text
gvkey
cik10 or cik_string or cik
fyear or fiscal_year or year
ffi48
```

The crawler extracts unique CIKs from this panel and writes the cleaned CIK list to:

```text
output/sample_cik.csv
```

The peer-variable builder later uses the same firm-year panel to merge topic variables and construct peer exposure.
Rows without a valid CIK are retained in the peer-variable output. They receive zero own SEC comment exposure when no topic match is available, preserving the original panel's industry-year composition.

## 2. SEC Comment-Letter Download

The crawler uses the SEC company submissions API to identify filings for each CIK. It keeps only form type:

```text
UPLOAD
```

`UPLOAD` is the SEC-originated comment letter. The code excludes `CORRESP` because company responses are not the intended source of regulatory disclosure pressure.

For each retained filing, the crawler downloads the primary document from the SEC archive. The raw source document is stored under:

```text
output/raw_filings/
```

The extracted plain text is stored under:

```text
output/comment_texts/
```

The crawler distinguishes PDF, TXT, and HTML source documents. PDF letters are extracted with `pdfminer.six`; TXT and HTML documents are decoded directly, with HTML tags stripped. The filing-level metadata records `source_doc_type`, `extraction_method`, `raw_file`, `text_file`, `text_length`, `text_extraction_error`, and `text_starts_raw_pdf`.

The raw-PDF guard is important. If extracted text still begins with `%PDF`, the code treats the extraction as failed and does not silently pass raw PDF bytes to the classifier.

The crawler is resumable. Existing extracted text is reused only when the text file is non-empty and does not begin with `%PDF`. If a previous run left an empty file or raw PDF text, the document is retried.

Use a descriptive SEC User-Agent and a reasonable request delay. The default workflow is intentionally serial and resumable.

## 3. Text Classification

The classifier works at the comment-item level when a letter can be split into numbered items. If splitting fails, the full letter is treated as one item.

The classifier uses three steps.

### Step 1: MD&A Liquidity And Capital Resources Context

This step identifies comments about disclosure contexts most closely related to financial constraints:

```text
MD&A
management's discussion and analysis
liquidity
capital resources
cash requirements
cash needs
working capital
cash flows
financing arrangements
known trends
known demands
known commitments
known uncertainties
```

### Step 2: Equity-Market-Access Language

This step identifies language about access to equity financing or capital markets:

```text
equity financing
equity offering
public offering
follow-on offering
registered offering
shelf registration
shelf offering
at-the-market
ATM program
sale of shares
issuance of shares
stock issuance
share issuance
equity securities
capital markets
raise capital
private placement
```

### Step 3: Financing-Constraint Language

This step identifies language about difficulty obtaining financing or supporting operations:

```text
ability to obtain
ability to raise
ability to access
access to capital
may not be able
unable to
difficulty
adverse market conditions
limited access
additional financing
additional capital
need to raise
no assurance
going concern
fund our operations
meet our obligations
cash runway
substantial doubt
```

## 4. Equity-FCE Comment Rule

For each comment item, the code first checks whether each text step appears. It then requires cross-topic co-occurrence.

A comment item is classified as equity-FCE if equity-market-access language appears with liquidity/capital-resources language, with financing-constraint language, or within a local text window of either step.

The local window is 900 characters.

This avoids classifying isolated equity-offering language as equity-FCE. For example, a routine registration comment about common stock is not enough. The equity-market-access language must be connected to liquidity, capital resources, or financing constraints.

## 5. Firm-Year SEC Equity Disclosure Pressure

The item-level classifications are aggregated to the letter level and then to the firm-year level.

The main firm-year exposure is **SEC Equity Disclosure Pressure**:

```text
own_eq_any_minus_debt_fce_broad
  = Equity-FCE Comment Exposure - Debt-FCE Comment Exposure
```

This is an own-firm, own-year measure. It is not lagged and it is not leave-one-out. It is useful as an intermediate output because it records whether the SEC directly pressured the firm to clarify equity-market access in liquidity or financing-constraint settings.

The debt component is built with analogous debt-financing terms. Netting out debt-FCE comments helps separate equity-oriented disclosure pressure from general financing pressure.

## 6. Peer SEC Equity Disclosure Pressure

For firm `i` in industry `g` and year `t`, the final peer variable is:

```text
Peer SEC Equity Disclosure Pressure(i,t)
  = average of own_eq_any_minus_debt_fce_broad(j,t-1)
    for all peer firms j != i in industry g
```

The default main peer group is FF48.

The main output variable is:

```text
peer_sec_equity_pressure_ff48
```

This variable is:

- lagged by one year;
- leave-one-out;
- based on peers in the same FF48 industry;
- based on the firm-year SEC Equity Disclosure Pressure variable above.

## 7. Validation Checks

Recommended technical checks:

1. Confirm `sample_cik.csv` has non-empty 10-digit CIKs.
2. Confirm downloaded filing-level output contains only `UPLOAD`.
3. Confirm `comment_year` is within the intended sample window.
4. Confirm `text_starts_raw_pdf` is zero before running the classifier.
5. Inspect examples with positive equity-FCE flags, separately for PDF-extracted and TXT/HTML letters.
6. Inspect false-positive flags around compensation, EPS, and generic common-stock comments.
7. Confirm the preferred peer variable is missing when an industry-year has no peers.
