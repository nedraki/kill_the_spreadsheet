"""Deterministic, conservative cleaning with lossless row quarantine.

The four-item public result is retained. DataFrame attrs contain positional column
mapping and quarantine metadata names; index labels are never used as row IDs.
"""
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import math
import numbers
import re
import unicodedata

import pandas as pd

CURRENCY_MAP = {'C$': '_cad_', 'A$': '_aud_', '€': '_eur_', '$': '_usd_',
                '£': '_gbp_', '¥': '_jpy_', '₹': '_inr_', '₩': '_krw_', '₽': '_rub_'}
TRUE_VALUES = {'true', '1', 'yes', 'y', 't', 'active', 'on'}
FALSE_VALUES = {'false', '0', 'no', 'n', 'f', 'inactive', 'off'}
TYPES = {'STRING', 'BOOLEAN', 'INTEGER', 'NUMERIC', 'DATE', 'DATETIME', 'TIMESTAMP'}
INT_MIN, INT_MAX = -(2**63), 2**63 - 1
NUMERIC_MAX = Decimal('99999999999999999999999999999.999999999')
RESERVED = ('_table_', '_file_', '_partition', '_row_timestamp', '__root__',
            '_colidentifier', '_change_sequence_number', '_change_type',
            '_change_timestamp', '_field_')


def clean_bigquery_column(col_name):
    name = str(col_name)
    for symbol, code in CURRENCY_MAP.items():
        name = name.replace(symbol, code)
    name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode()
    name = re.sub(r'[^a-zA-Z0-9_]+', '_', name).strip('_').lower() or 'unnamed_col'
    if name[0].isdigit():
        name = '_' + name
    if name.startswith(RESERVED):
        name = 'col' + name
    return name[:300]


def unique_column_names(columns):
    """Allocate names by position; even repeated source labels remain distinct."""
    used, result = set(), []
    for column in columns:
        base = clean_bigquery_column(column)
        name, suffix = base, 2
        while name in used:
            tail = f'_{suffix}'
            name = base[:300 - len(tail)] + tail
            suffix += 1
        used.add(name)
        result.append(name)
    return result


def is_missing(value):
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    return isinstance(value, numbers.Real) and not isinstance(value, numbers.Integral) and math.isnan(value)


def _text(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _decimal(value, number_format):
    if isinstance(value, bool):
        raise ValueError('Boolean is not a number')
    text = str(value).strip()
    if number_format != 'plain':
        # Explicit locale opt-in; separators must form valid groups.
        text = re.sub(r'^(?:C\$|A\$|[$€£])\s*', '', text)
        if text.startswith('(') and text.endswith(')'):
            text = '-' + text[1:-1]
        grouping, point = (',', '.') if number_format == 'us' else ('.', ',')
        pattern = rf'[+-]?(?:[0-9]+|[0-9]{{1,3}}(?:{re.escape(grouping)}[0-9]{{3}})+)(?:{re.escape(point)}[0-9]+)?'
        if not re.fullmatch(pattern, text):
            raise ValueError('Invalid numeric grouping')
        text = text.replace(grouping, '').replace(point, '.')
    if len(text) > 128 or not re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?', text):
        raise ValueError('Not a canonical number')
    result = Decimal(text)
    if not result.is_finite():
        raise ValueError('Non-finite number')
    return result


def _numeric_fits(value):
    # Decimal comparisons/tuple inspection avoid context-dependent rounding.
    _, digits, exponent = value.as_tuple()
    trailing = 0
    for digit in reversed(digits):
        if digit != 0:
            break
        trailing += 1
    return value.copy_abs() <= NUMERIC_MAX and (not value or exponent + trailing >= -9)


def _datetime(value, date_format):
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    text = str(value).strip()
    if date_format:
        # Require complete date components; disallow implicit current/default year.
        if not all(code in date_format for code in ('%Y', '%m', '%d')):
            raise ValueError('date_format must include %Y, %m and %d')
        return datetime.strptime(text, date_format)
    if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}(?:[T ][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})?)?', text):
        raise ValueError('Not a complete ISO date or datetime')
    return datetime.fromisoformat(text.replace('Z', '+00:00'))


def _convert(value, kind, number_format, date_format):
    if is_missing(value):
        return None
    if isinstance(value, numbers.Real) and not isinstance(value, numbers.Integral) and not math.isfinite(value):
        raise ValueError('Non-finite source number')
    if isinstance(value, Decimal) and not value.is_finite():
        raise ValueError('Non-finite source number')
    if isinstance(value, (dict, list, tuple, set)):
        raise ValueError('Nested values are unsupported')
    if kind == 'STRING':
        return _text(value)
    if kind == 'BOOLEAN':
        text = str(value).strip().lower()
        if text not in TRUE_VALUES | FALSE_VALUES:
            raise ValueError('Not a boolean')
        return text in TRUE_VALUES
    if kind in {'INTEGER', 'NUMERIC'}:
        number = _decimal(value, number_format)
        if kind == 'INTEGER':
            if number != number.to_integral_value() or not INT_MIN <= number <= INT_MAX:
                raise ValueError('Outside exact INT64 range')
            return int(number)
        if not _numeric_fits(number):
            raise ValueError('Outside exact BigQuery NUMERIC precision/range')
        return number
    parsed = _datetime(value, date_format)
    aware = parsed.utcoffset() is not None
    if kind == 'TIMESTAMP':
        if not aware:
            raise ValueError('TIMESTAMP requires an explicit timezone')
        return parsed.astimezone(timezone.utc)
    if aware:
        raise ValueError('Timezone cannot be discarded')
    if kind == 'DATE':
        if parsed.time() != datetime.min.time():
            raise ValueError('Time cannot be discarded')
        return parsed.date()
    return parsed


def _attempt(value, kind, number_format, date_format):
    try:
        return _convert(value, kind, number_format, date_format), None
    except (ValueError, TypeError, OverflowError, InvalidOperation) as exc:
        return None, str(exc)


def _infer(values, threshold, number_format, date_format):
    present = [v for v in values if not is_missing(v)]
    if not present:
        return 'STRING'
    if all(isinstance(v, bool) or str(v).strip().lower() in {'true', 'false'} for v in present):
        return 'BOOLEAN'
    strings = [v.strip() for v in present if isinstance(v, str)]
    # Preserve IDs and ambiguous numeric notation even below the inference threshold.
    protected = any(re.fullmatch(r'[+-]?0[0-9]+', s) for s in strings)
    protected |= bool(strings) and len(strings) == len(present) and set(strings) <= {'0', '1'}
    if number_format == 'plain':
        protected |= any(re.search(r'[0-9][,\s][0-9]|[$€£]', s) for s in strings)
    if not protected:
        numeric = []
        for value in present:
            try:
                numeric.append(_decimal(value, number_format))
            except (ValueError, InvalidOperation):
                pass
        if len(numeric) / len(present) >= threshold:
            if all(v == v.to_integral_value() for v in numeric):
                return 'INTEGER' if all(INT_MIN <= v <= INT_MAX for v in numeric) else 'STRING'
            return 'NUMERIC' if all(_numeric_fits(v) for v in numeric) else 'STRING'
    parsed = [_attempt(v, 'TIMESTAMP', number_format, date_format) for v in present]
    naive = [_attempt(v, 'DATETIME', number_format, date_format) for v in present]
    # Mixed timezone semantics cannot be safely inferred.
    if any(e is None for _, e in parsed) and any(e is None for _, e in naive):
        return 'STRING'
    for kind in ('DATE', 'DATETIME', 'TIMESTAMP'):
        results = [_attempt(v, kind, number_format, date_format) for v in present]
        # Do not infer DATE by discarding time-bearing minority rows.
        if kind == 'DATE' and any(e and 'Time cannot' in e for _, e in results):
            continue
        if sum(error is None for _, error in results) / len(present) >= threshold:
            return kind
    return 'STRING'


def clean_generic_dataframe(df_raw, TYPE_INFERENCE_THRESHOLD=0.90, *,
                            column_types=None, null_values=(), number_format='plain',
                            date_format=None):
    """Clean without mutating input; only explicitly configured literals become null.

    column_types keys use sanitized, unique output names. Locale parsing and date
    formats are explicit opt-ins. All-null columns/rows are retained. The accepted
    and quarantine outputs partition physical input rows, even with duplicate indices.
    """
    if not isinstance(df_raw, pd.DataFrame):
        raise ValueError('Input must be a pandas DataFrame')
    if not isinstance(TYPE_INFERENCE_THRESHOLD, numbers.Real) or not 0 < TYPE_INFERENCE_THRESHOLD <= 1:
        raise ValueError('Threshold must be in (0, 1]')
    if number_format not in {'plain', 'us', 'eu'}:
        raise ValueError('number_format must be plain, us or eu')
    if date_format and not all(code in date_format for code in ('%Y', '%m', '%d')):
        raise ValueError('date_format must include %Y, %m and %d')
    names = unique_column_names(df_raw.columns)
    overrides = column_types or {}
    if set(overrides) - set(names) or set(overrides.values()) - TYPES:
        raise ValueError('Unknown column or unsupported type override')
    nulls = {str(v).strip().casefold() for v in null_values}
    report, columns, errors = {}, {}, [[] for _ in range(len(df_raw))]
    for position, name in enumerate(names):
        values = [None if isinstance(v, str) and v.strip().casefold() in nulls else v
                  for v in df_raw.iloc[:, position].tolist()]
        kind = overrides.get(name) or _infer(values, TYPE_INFERENCE_THRESHOLD, number_format, date_format)
        report[name] = kind
        converted = []
        for row, value in enumerate(values):
            output, error = _attempt(value, kind, number_format, date_format)
            converted.append(output)
            if error:
                errors[row].append(f"Column '{name}': {error} (expected {kind})")
        columns[name] = pd.Series(converted, dtype=object)
    cleaned = pd.DataFrame(columns, index=range(len(df_raw)))
    cleaned.index = df_raw.index.copy()
    accepted = [pos for pos, reasons in enumerate(errors) if not reasons]
    rejected = [pos for pos, reasons in enumerate(errors) if reasons]
    ready = cleaned.iloc[accepted].copy()
    comparison = df_raw.copy(deep=True)
    comparison.columns = names
    combined_names = unique_column_names(names + [f'{name}_clean' for name in names])
    for pos, name in enumerate(names):
        comparison[combined_names[len(names) + pos]] = cleaned[name].to_numpy()
    quarantine = df_raw.iloc[rejected].copy(deep=True)
    metadata = unique_column_names(list(df_raw.columns) + ['source_position', 'original_index', 'quarantine_reason'])[-3:]
    quarantine[metadata[0]] = rejected
    quarantine[metadata[1]] = [df_raw.index[pos] for pos in rejected]
    quarantine[metadata[2]] = ['; '.join(errors[pos]) for pos in rejected]
    quarantine.attrs['metadata_columns'] = dict(zip(('source_position', 'original_index', 'quarantine_reason'), metadata))
    mapping = [{'position': pos, 'original': str(original), 'cleaned': name}
               for pos, (original, name) in enumerate(zip(df_raw.columns, names))]
    for frame in (comparison, ready, quarantine):
        frame.attrs['column_mapping'] = mapping
    return comparison, ready, quarantine, report
