# Data integrity audit — 2026-11-15

Scope: application/library code, dependency declarations, Excel ingestion, JSONL
serialization, Streamlit interaction, documentation, and delivery/testing configuration
at baseline `216b941`. No tests or CI existed. The audit prioritized silent changes to
values and loss of source rows/columns over cosmetic cleanup.

## Findings and remediation

| Critical issue | Reproduced failure | Fix |
| --- | --- | --- |
| [#1](https://github.com/nedraki/kill_the_spreadsheet/issues/1) | Status/null tokens erased; IDs, locale numbers and relative dates changed | Conservative text preservation; explicit locale, type, date-format and null-token rules |
| [#2](https://github.com/nedraki/kill_the_spreadsheet/issues/2) | Float intermediates rounded large integers and decimals | Exact integer/Decimal parsing and serialization, supported-range validation |
| [#3](https://github.com/nedraki/kill_the_spreadsheet/issues/3) | Rejected rows remained load-ready; duplicate indices expanded quarantine | Accepted/rejected partition by physical position; intact source rows and reasons |
| [#4](https://github.com/nedraki/kill_the_spreadsheet/issues/4) | Header collisions, `_clean` fields and empty rows/columns lost data | Unique positional headers, collision-safe metadata/comparison, preserved table shape |
| [#6](https://github.com/nedraki/kill_the_spreadsheet/issues/6) | Export mutated input, rounded decimals, hid errors, lacked a schema | Shared strict serializer, explicit BigQuery schema, separate positional recovery export |
| [#7](https://github.com/nedraki/kill_the_spreadsheet/issues/7) | Excel defaults erased literal text, rewrote headers and hid formulas/errors | Shared XLSX reader, sheet/header selection, unsafe-cell coordinates, source precision guards |
| [#9](https://github.com/nedraki/kill_the_spreadsheet/issues/9) | Currency symbols disappeared from financially incomparable amounts | Mixed denominations stay strings; numeric overrides require separation by currency |

The first cleaner regression run had **20 failures and 1 pass**. Four export and four
workbook regressions were separately reproduced before their fixes. Later integration
checks exposed native numeric values being reinterpreted under locale rules, mixed
currency loss, header normalization boundaries, and Excel's fictitious 1900 leap day.
Each now has regression coverage.

## Validation

The final local suite has **78 passing tests** and **96.88% statement coverage** across
the application and libraries (Streamlit application: 100% statement coverage). This
is statement coverage, not proof that every branch or input combination is safe. CI
runs the locked environment on Python 3.12 and 3.13 with a 90% coverage floor.

| Test group | Scenarios |
| --- | --- |
| Cleaning | Literal nulls/statuses, leading zeros, boolean ambiguity, numeric locale rules, exact INT64/NUMERIC bounds, nulls, invalid thresholds, explicit overrides, mixed currencies, nonfinite/nested inputs |
| Property tests | Generated INT64 values retain precision; arbitrary Unicode/long/colliding headers remain unique, valid and stable |
| Dates | ISO and configured complete dates, relative/incomplete dates retained, timezone preservation, mixed timezone semantics, time-bearing minority values, sub-microsecond rejection |
| Quarantine | Failed rows absent from accepted data, complete row partition, original values, duplicate/mixed indices, metadata collisions, multiple field errors |
| Export | Exact decimal/large integer round trips, matching schema, Unicode/escaped newlines, true nulls, empty files, non-mutating caller data, meaningful failures, original rejected cells |
| Real XLSX | Multi-sheet/header offset, merged preambles, duplicate/blank headers, formula/error/merged table cells, zero-padded numeric displays, oversized numeric cells, Windows 1900 and Mac 1904 calendars, hidden rows, file and cell limits |
| Streamlit | No upload, successful upload, rule changes, rejected-row recovery, duplicate-header previews, empty/all-rejected tables, invalid rules, unsafe replacement uploads and removal of stale downloads |

A generated **10,000-row, five-column workbook** completed read → clean → JSONL in
**0.736 seconds** on the audit machine, producing 10,000 accepted rows, no rejections,
1,100,000 JSONL bytes, intact eight-character identifiers, and exact nine-place amounts.
This is a local smoke benchmark, not a production performance guarantee.

## Delivery

All changes use `codex/` branches and PRs; no direct changes are pushed to main.

- [PR #5](https://github.com/nedraki/kill_the_spreadsheet/pull/5): cleaning, tests and CI.
- [PR #8](https://github.com/nedraki/kill_the_spreadsheet/pull/8): exact export and schema.
- Final workbook/UI PR: strict ingestion, end-to-end/UI tests, mixed currencies,
  coverage gate, updated workflow documentation and version 0.2.0.

## Boundaries and remaining operational checks

- **No live BigQuery load was run.** No target project/dataset was supplied. JSONL and
  schema are tested locally against the documented supported formats. Before production,
  load a representative synthetic workbook with the supplied schema and zero tolerated
  bad records. Do not enable schema autodetection.
- Inference cannot establish business meaning. Numeric-looking IDs without leading
  zeros may infer INTEGER; analysts should explicitly require STRING. A 100% threshold
  can leave mixed data as STRING; explicit type rules enforce a required schema.
- Upstream Excel/float precision loss cannot be recovered. Large native Excel numbers
  and zero-padded numeric displays are blocked. Dates use the reader's representation;
  ambiguous Windows-calendar 1900-02-28 values require verified ISO source text.
- Formula/error and merged table cells block export. The app does not calculate formulas
  or trust cached results. Legacy `.xls` is explicitly unsupported; save as `.xlsx` first.
- One selected worksheet table is processed per run. Footers/totals/embedded tables
  require source separation. Hidden rows/columns are included. Blank rows inside the
  detected table and all-null fields are preserved; no deduplication or imputation occurs.
- Processing remains in memory with explicit compressed/expanded/cell limits. Production
  concurrency, authentication, infrastructure hardening, malware scanning, dependency
  vulnerability scanning, and large-file streaming were not validated by this functional
  data-integrity audit. There is no claim of a comprehensive security certification.
- Recovery files retain source cell text/types, headers and Excel row references; retain
  the original workbook to preserve formatting and other workbook metadata.

References: [BigQuery schemas](https://docs.cloud.google.com/bigquery/docs/schemas),
[BigQuery JSON loading](https://docs.cloud.google.com/bigquery/docs/loading-data-cloud-storage-json).
