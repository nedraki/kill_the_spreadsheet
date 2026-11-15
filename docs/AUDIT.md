# Data integrity audit — 2026-11-15

Scope: all tracked application/library code, dependency declarations, Excel ingestion,
JSONL serialization, UI flow, and delivery/testing configuration at baseline `216b941`.
No tests or CI existed. The first regression run had **20 failures, 1 pass**.

## Reproduced critical findings

| Issue | Failure | Remediation |
| --- | --- | --- |
| [#1](https://github.com/nedraki/kill_the_spreadsheet/issues/1) | Literal null tokens, IDs, locale numbers and relative dates changed silently | Preserve ambiguous text; explicit locale, type, date-format and null-token options |
| [#2](https://github.com/nedraki/kill_the_spreadsheet/issues/2) | Float intermediates rounded integers and decimals | Exact Python integers/Decimal; enforce INT64/NUMERIC limits; exact export follow-up |
| [#3](https://github.com/nedraki/kill_the_spreadsheet/issues/3) | Failed rows remained in load-ready output; duplicate indices expanded quarantine | Partition by physical position, retain complete rejected source rows |
| [#4](https://github.com/nedraki/kill_the_spreadsheet/issues/4) | Header collisions, `_clean` suffixes, empty rows/columns lost data | Unique positional headers, retained shape, mapping and collision-safe metadata |

## Test design

Regression examples cover the concrete failures above. Property tests generate INT64
values and arbitrary Unicode/colliding headers. Additional boundaries cover exact
NUMERIC scale, range overflow, explicit locale/date rules, mixed timezone semantics,
minority fractional/time values, source immutability, duplicate/mixed index labels,
and quarantine metadata collisions. CI runs the locked environment on Python 3.12/3.13.

## Contract

Automatic inference is conservative, not proof of business meaning. Leading zeros,
ambiguous number formatting, statuses, incomplete/relative dates and 0/1 strings stay
text. Only actual missing cells are null by default. Explicit column rules can require
a type; rejected values then quarantine the entire source row. Thresholds determine
when a type can be inferred, never whether failed rows are allowed into the output.
All physical input rows and columns are accounted for; no deduplication, imputation,
whitespace stripping of text, or business-rule corrections occur automatically.

Exact BigQuery NUMERIC supports at most nine fractional digits and 29 integer digits.
Values outside supported ranges remain strings under inference, or quarantine with
an explicit numeric rule. Already-rounded values supplied as Python floats cannot
be reconstructed. Workbook/export/UI findings and release validation follow below.

References: [BigQuery schemas](https://docs.cloud.google.com/bigquery/docs/schemas),
[JSON loading](https://docs.cloud.google.com/bigquery/docs/loading-data-cloud-storage-json).

## Export findings and fix

[#6](https://github.com/nedraki/kill_the_spreadsheet/issues/6): all four initial export
regressions failed (input mutation, decimal rounding, unnamed stream failure, hidden
exceptions). A single strict serializer now feeds the UI and library; exact NUMERIC
values and integers outside the JSON safe range are strings, accompanied by a matching
BigQuery schema. Schema autodetection must be disabled. This completes the export part
of #2. Recovery JSONL keeps rejected cells positionally, even for duplicate source
headers. Unsupported values and sub-microsecond datetimes cannot silently truncate.
The expanded suite passes 50 tests locally; CI checks both supported Python versions.

[#7](https://github.com/nedraki/kill_the_spreadsheet/issues/7): default Excel ingestion
turns `00123`/`NA` into `123.0`/null, erases `NULL`, and can hide formula/error cells.
Workbook ingestion and UI integration are the next release group.
