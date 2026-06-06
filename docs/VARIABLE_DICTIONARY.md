# Variable Dictionary

This file documents the main variables created by the pipeline.

## Input Panel

`cik10`  
10-digit CIK with leading zeros.

`gvkey`  
Firm identifier from the user's panel.

`fyear`  
Fiscal year used for firm-year merging and lag construction. The script can create it from `fiscal_year` or `year`.

`ffi48`  
FF48 industry code used by the default peer-variable construction. Users can pass another industry or peer group column through `--peer-groups`.

## Filing-Level Download Output

`cik10`  
10-digit SEC CIK.

`accession`  
SEC accession number.

`filing_date_public`  
Public filing date from EDGAR metadata.

`comment_year`  
Calendar year used for firm-year aggregation.

`form`  
SEC form type. The main pipeline keeps `UPLOAD`.

`url`  
SEC archive URL for the downloaded letter.

`text_file`  
Local path to the downloaded text file.

## Item-Level Classification

`mda_liq_comment`  
Equals 1 if the comment item contains MD&A, liquidity, capital-resources, cash, funding, or known-uncertainty language.

`equity_market_access_comment`  
Equals 1 if the item contains equity-financing or capital-market-access language.

`constraint_comment`  
Equals 1 if the item contains financing-constraint language.

`equity_liq_near_window`  
Equals 1 if equity-market-access language appears within the local window of MD&A liquidity/capital-resources language.

`equity_constraint_near_window`  
Equals 1 if equity-market-access language appears within the local window of financing-constraint language.

`eq_fce_broad_comment`  
Equals 1 if the item satisfies the main equity-FCE classification rule.

`debt_fce_broad_comment`  
Equals 1 if the item satisfies the debt-FCE classification rule.

`possible_equity_false_positive`  
Audit flag for items where equity words likely appear in compensation, EPS, or generic share-count contexts rather than equity financing.

## Letter-Level Classification

`own_eq_fce_broad_comment`  
Equals 1 if any item in the SEC letter satisfies the equity-FCE rule.

`own_eq_fce_letter_broad_comment`  
Equals 1 if the same letter contains both liquidity/capital-resources language and equity-market-access language, even if they appear in different items.

`own_eq_fce_any_broad_comment`  
Equals 1 if either item-level or letter-level equity-FCE exposure is present.

`own_debt_fce_broad_comment`  
Equals 1 if debt-FCE exposure is present.

## Firm-Year Classification

`own_eq_fce_any_broad_comment`  
Equals 1 if the firm-year has at least one SEC letter classified as equity-FCE by either the item-level or letter-level rule.

`own_debt_fce_broad_comment`  
Equals 1 if the firm-year has at least one SEC letter classified as debt-FCE.

`own_eq_any_minus_debt_fce_broad`  
Main firm-year **SEC Equity Disclosure Pressure** variable. It measures own-firm SEC comment exposure about equity-market access in liquidity or financing-constraint settings, net of debt-oriented financing pressure:

```text
own_eq_fce_any_broad_comment - own_debt_fce_broad_comment
```

This variable is an intermediate output and is retained in the final merged panel. It is the source variable used to construct peer exposure.

`n_eq_fce_broad_comment_items`  
Number of equity-FCE classified comment items in the firm-year.

`n_debt_fce_broad_comment_items`  
Number of debt-FCE classified comment items in the firm-year.

`n_eq_minus_debt_fce_broad_items`  
Item-count version of equity-FCE minus debt-FCE exposure.

## Peer Variables

`peer_sec_equity_pressure_ff48`  
One-year-lagged leave-one-out FF48 peer average of `own_eq_any_minus_debt_fce_broad`. This is the main **Peer SEC Equity Disclosure Pressure** variable.

Variables with `sic3` suffix are analogous leave-one-out peer averages based on SIC3 groups.
