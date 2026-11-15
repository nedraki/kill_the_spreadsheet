# Kill the spreadsheet

A Streamlit app for analysts who need to clean an Excel table and prepare a
reviewable BigQuery load. Cleaning uses deterministic rules. Ambiguous values
stay text; failed conversions go to a separate recovery file.

## Run and test

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync --locked
uv run streamlit run main.py
uv run pytest -q
```

CI runs regression, property, real-workbook and Streamlit UI tests on Python
3.12 and 3.13. See [the audit](docs/AUDIT.md) for findings and validation limits.

## Analyst workflow

1. Upload an `.xlsx` workbook, choose a worksheet and its header row. Rows above
   the header are excluded explicitly. Hidden rows and columns in the selected
   table are included; Excel filters do not remove records.
2. Review the source data and positional column mapping. Duplicate, blank,
   non-string and long headers get distinct BigQuery-compatible names.
3. Choose parsing rules. The defaults retain ambiguous numbers, dates and text.
   Set European/US number formatting or a complete date format only when you know
   the source convention. Optional null tokens are case-insensitive.
4. Set column types when business meaning matters. For example,
   `{"customer_id":"STRING", "amount":"NUMERIC", "booked_on":"DATE"}` uses the
   export column names. A required type quarantines every row that fails it.
5. Review the inferred schema, original/cleaned comparison and row counts.
   Download accepted JSONL, its schema, the cleaning report and any rejected rows.
6. Load with the supplied schema and **disable schema autodetection**:

```sh
bq load --source_format=NEWLINE_DELIMITED_JSON --max_bad_records=0 \
  PROJECT:DATASET.TABLE accepted.jsonl accepted.schema.json
```

Do not load `.rejected.jsonl` as the table. It is a recovery file containing
original cell text, source types, positional header mapping, Excel row numbers
and rejection reasons. Resolve those rows in the source and run cleaning again.

## Data preservation rules

- Literal `NA`, `NULL`, `pending`, `unknown`, empty text and similar strings are
  retained unless you explicitly configure them as null tokens. Empty Excel cells
  remain null. Empty rows inside the table and all-null columns are retained.
- Leading-zero identifiers, ambiguous grouped numbers, 0/1 strings, relative
  dates and incomplete dates stay strings. String whitespace is retained.
- Mixed currency symbols never disappear into a single numeric column: inference
  retains the text, and numeric overrides require splitting by currency first.
- Canonical numbers use exact integers/decimals. There are no float conversion
  steps in the cleaner or serializer. BigQuery NUMERIC is limited to 29 integer
  and 9 fractional digits. Unsupported precision/range stays text by default and
  fails an explicit numeric rule.
- Exact NUMERICs and integers outside JSON's safe integer range are serialized
  as strings. The accompanying schema gives them the intended BigQuery types.
- ISO dates and datetimes can be inferred. TIMESTAMP requires an explicit
  timezone; mixed aware/naive values stay text. Time and timezone information
  cannot silently disappear. Sub-microsecond precision is not truncated.
- The default inference threshold is 100%. A mixed amount/text column therefore
  stays STRING. Lowering the threshold permits inference from a majority and
  rejects failing rows. Use an explicit column type to enforce a required schema.
- Every source field has a positional mapping; accepted and rejected physical
  rows form a complete partition. Duplicate index labels do not identify rows.
- No automatic deduplication, imputation, business-rule correction or formula
  evaluation occurs. Inputs are not mutated.

## Supported input and limits

Only `.xlsx` is supported

Formula/error cells and merged cells in the selected table block export with
coordinates. Replace formulas with verified values and resolve errors yourself;
cached formula results may be missing or stale. Zero-padded numeric display formats
also require identifiers to be stored as text. Numeric Excel cells at or above
10^15 in magnitude are blocked; obtain the exact original values as text. Dates
decoding to 1900-02-28 in the Windows calendar require verified ISO text because
Excel serials 59 and the fictitious leap day 60 otherwise decode identically.

Upload limits are 10 MiB compressed, 25 MiB expanded and 250,000 worksheet cells,
including formatted cells. These bound the in-memory workflow; large-file streaming
is not implemented. Workbooks are not sent to BigQuery by this app.

Excel and floating-point inputs may already have lost precision before upload;
no cleaner can recover that information. Date values follow the workbook calendar
and the Excel reader's representation. Inference cannot establish business meaning:
review the schema and use STRING overrides for identifiers even if they contain
only digits. No automated suite guarantees correctness for every workbook.

## Library API

```python
from src_lib.excel_reader import read_excel
from src_lib.clean_da_mess import clean_generic_dataframe
from src_lib.spreadsheet_to_jsonl import bigquery_schema, dataframe_to_jsonl

raw = read_excel('source.xlsx', sheet_name='Transactions', header_row=2)
comparison, accepted, rejected, types = clean_generic_dataframe(
    raw,
    column_types={'customer_id': 'STRING', 'amount': 'NUMERIC'},
    number_format='eu',
)
jsonl = dataframe_to_jsonl(accepted, types)
schema = bigquery_schema(types)
```

The four-item cleaner return is retained. The library threshold defaults to 0.90
for compatibility; the UI defaults to 1.0. `excel_to_jsonl` is a convenience wrapper
that raises if any row is rejected, rather than silently returning partial data.
Exceptions are propagated instead of returning `None`. Schema downloads use
STRING, BOOLEAN, INTEGER, NUMERIC, DATE, DATETIME and TIMESTAMP (all NULLABLE).
