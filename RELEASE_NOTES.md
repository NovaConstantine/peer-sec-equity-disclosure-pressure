# Release Notes

## v0.1-pre

This is a publish-before-final draft of the Peer SEC Equity Disclosure Pressure code.

Included:

- firm-year panel input;
- automatic CIK extraction from the panel;
- SEC `UPLOAD` comment-letter crawler;
- PDF-aware text extraction with raw-PDF safeguards;
- rule-based SEC comment-letter topic classifier;
- firm-year topic aggregation;
- firm-year SEC Equity Disclosure Pressure as an intermediate output;
- lagged leave-one-out peer variable construction;
- small fake example files for local testing.

Not included:

- regression code;
- paper-specific tables;
- downloaded SEC text files;
- generated output data.

The main firm-year intermediate variable is:

```text
own_eq_any_minus_debt_fce_broad
```

The main peer variable is:

```text
peer_sec_equity_pressure_ff48
```
