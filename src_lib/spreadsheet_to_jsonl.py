"""Strict JSONL and matching BigQuery schema serialization."""
from datetime import date, datetime
from decimal import Decimal
import json
from os import PathLike

import pandas as pd

from src_lib.clean_da_mess import (
    TYPES, _convert, clean_generic_dataframe, is_missing, unique_column_names,
)


def bigquery_schema(type_report):
    names = list(type_report)
    if unique_column_names(names) != names:
        raise ValueError('Schema requires unique, sanitized column names')
    if set(type_report.values()) - TYPES:
        raise ValueError('Unsupported BigQuery type')
    return [{'name': name, 'type': kind, 'mode': 'NULLABLE'} for name, kind in type_report.items()]


def dataframe_to_jsonl(frame, type_report):
    """Serialize cleaned data without float intermediates or pandas rounding.

    Exact NUMERICs and integers outside the JSON safe range are quoted; load them
    with bigquery_schema(type_report), never schema autodetection.
    """
    if not isinstance(frame, pd.DataFrame):
        raise TypeError('Expected a pandas DataFrame')
    schema = bigquery_schema(type_report)
    if frame.columns.tolist() != [field['name'] for field in schema]:
        raise ValueError('Data columns and schema must match in name and order')
    lines = []
    for position, row in enumerate(frame.itertuples(index=False, name=None)):
        record = {}
        for (name, kind), value in zip(type_report.items(), row):
            try:
                value = _convert(value, kind, 'plain', None)
            except (ValueError, TypeError, OverflowError) as exc:
                raise ValueError(f'Row {position}, column {name}: {exc}') from exc
            if isinstance(value, Decimal):
                value = format(value, 'f') if value else '0'
            elif isinstance(value, int) and not isinstance(value, bool) and abs(value) > 2**53 - 1:
                value = str(value)
            elif isinstance(value, (date, datetime)):
                value = value.isoformat()
            record[name] = value
        lines.append(json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(',', ':')))
    return '\n'.join(lines) + ('\n' if lines else '')


def quarantine_to_jsonl(frame):
    """Export original cells positionally, retaining duplicate headers and metadata.

    This is a recovery artifact, not a BigQuery load file. Cell text and source
    Python types are recorded without interpreting or rounding rejected values.
    """
    metadata = frame.attrs['metadata_columns']
    mapping = frame.attrs['column_mapping']
    records = []
    for row in frame.itertuples(index=False, name=None):
        cells = []
        for field, value in zip(mapping, row):
            cells.append({**field, 'value': None if is_missing(value) else str(value),
                          'source_type': type(value).__name__})
        record = {'source_position': row[frame.columns.get_loc(metadata['source_position'])],
                  'original_index': str(row[frame.columns.get_loc(metadata['original_index'])]),
                  'reason': row[frame.columns.get_loc(metadata['quarantine_reason'])],
                  'cells': cells}
        records.append(json.dumps(record, ensure_ascii=False, allow_nan=False))
    return '\n'.join(records) + ('\n' if records else '')


def excel_to_jsonl(input_data, **cleaning_options):
    """Convenience conversion; raise on rejected rows rather than hiding data loss.

    Use clean_generic_dataframe and dataframe_to_jsonl directly to review and
    separately export quarantine. Exceptions are intentionally propagated.
    """
    if isinstance(input_data, pd.DataFrame):
        raw = input_data
    elif isinstance(input_data, (str, PathLike)) or hasattr(input_data, 'read'):
        raw = pd.read_excel(input_data, dtype=object, keep_default_na=False)
    else:
        raise TypeError('Expected a DataFrame, Excel path or binary file-like object')
    _, ready, quarantine, report = clean_generic_dataframe(raw, **cleaning_options)
    if not quarantine.empty:
        raise ValueError(f'{len(quarantine)} rows require quarantine; review with clean_generic_dataframe')
    return dataframe_to_jsonl(ready, report)
