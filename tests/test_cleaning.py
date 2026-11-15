from decimal import Decimal

import pandas as pd
import pytest
from hypothesis import given, strategies as st

from src_lib.clean_da_mess import clean_generic_dataframe


def clean(values, **kwargs):
    return clean_generic_dataframe(pd.DataFrame({'value': values}, dtype=object), **kwargs)


@pytest.mark.parametrize('values', [
    ['pending', 'unknown', 'NA', 'null', 'none', '--', ''],
    ['00123', '00456'], ['active', 'inactive'], ['0', '1'],
    ['1,25', '2,75'], ['1 2', '3 4'], ['tomorrow', 'yesterday'],
    ['01/02/2024', '03/04/2024'], ['March', 'April'],
])
def test_ambiguous_text_is_preserved(values):
    _, ready, quarantine, report = clean(values)
    assert ready['value'].tolist() == values
    assert report['value'] == 'STRING'
    assert quarantine.empty


def test_integer_precision_and_nulls():
    _, ready, _, report = clean(['9007199254740993', None, '9223372036854775807'])
    assert ready['value'].tolist() == [9007199254740993, None, 9223372036854775807]
    assert report['value'] == 'INTEGER'


def test_decimal_precision():
    _, ready, _, report = clean(['123.123456789', '0.000000001'])
    assert ready['value'].tolist() == [Decimal('123.123456789'), Decimal('0.000000001')]
    assert report['value'] == 'NUMERIC'


def test_failed_rows_are_excluded_and_original_rows_preserved():
    raw = pd.DataFrame({'amount': ['12'] * 9 + ['broken'], 'label': list('abcdefghij')})
    _, ready, quarantine, _ = clean_generic_dataframe(raw)
    assert len(ready) == 9
    assert quarantine['amount'].tolist() == ['broken']
    assert quarantine['label'].tolist() == ['j']


def test_duplicate_indices_do_not_expand_quarantine():
    raw = pd.DataFrame({'amount': ['12'] * 9 + ['broken']}, index=[7] * 10)
    _, ready, quarantine, _ = clean_generic_dataframe(raw)
    assert len(ready) == 9
    assert len(quarantine) == 1
    assert quarantine['amount'].tolist() == ['broken']


def test_collision_and_clean_suffix_do_not_drop_columns():
    raw = pd.DataFrame([['first', 'second', 'third', 'fourth']],
                       columns=['A B', 'A-B', 'a_b_clean', 'A B'])
    comparison, ready, _, report = clean_generic_dataframe(raw)
    assert ready.shape == (1, 4)
    assert ready.iloc[0].tolist() == raw.iloc[0].tolist()
    assert len(set(ready.columns)) == 4
    assert len(comparison.columns) == 8
    assert len(report) == 4


def test_empty_rows_and_columns_preserved():
    raw = pd.DataFrame({'empty': [None, None], 'other': ['text', None]}, dtype=object)
    _, ready, _, report = clean_generic_dataframe(raw)
    assert ready.shape == raw.shape
    assert report['empty'] == 'STRING'


@pytest.mark.parametrize('threshold', [0, -1, 1.1, float('nan')])
def test_invalid_threshold_rejected(threshold):
    with pytest.raises(ValueError):
        clean(['12'], TYPE_INFERENCE_THRESHOLD=threshold)


def test_no_input_mutation():
    raw = pd.DataFrame({'Name': ['pending', None]})
    snapshot = raw.copy(deep=True)
    clean_generic_dataframe(raw)
    pd.testing.assert_frame_equal(raw, snapshot)


@given(st.lists(st.integers(min_value=2, max_value=2**63 - 1), min_size=1, max_size=20))
def test_integer_property(values):
    _, ready, _, _ = clean([str(v) for v in values] + [None])
    assert ready['value'].tolist() == values + [None]


def test_fractional_minority_is_not_quarantined_as_integer():
    _, ready, quarantine, report = clean(['12'] * 9 + ['12.5'])
    assert report['value'] == 'NUMERIC'
    assert len(ready) == 10 and quarantine.empty
    assert ready.iloc[-1, 0] == Decimal('12.5')


@pytest.mark.parametrize('value', ['9223372036854775808', '0.1234567891', '1e1000'])
def test_out_of_range_numbers_preserved_as_text(value):
    _, ready, quarantine, report = clean([value])
    assert ready.iloc[0, 0] == value
    assert report['value'] == 'STRING' and quarantine.empty


@pytest.mark.parametrize('locale,values,expected', [
    ('eu', ['1.234,56', '2,75'], ['1234.56', '2.75']),
    ('us', ['$1,234.56', '(100.50)'], ['1234.56', '-100.50']),
])
def test_explicit_locale(locale, values, expected):
    _, ready, quarantine, _ = clean(values, number_format=locale)
    assert ready['value'].tolist() == list(map(Decimal, expected))
    assert quarantine.empty


def test_explicit_rules_and_no_silent_date_truncation():
    _, ready, quarantine, _ = clean(['01/02/2024', 'pending'],
        date_format='%d/%m/%Y', null_values=['pending'], column_types={'value': 'DATE'})
    assert str(ready.iloc[0, 0]) == '2024-02-01'
    assert ready.iloc[1, 0] is None and quarantine.empty
    _, ready, quarantine, _ = clean(['2024-01-01T12:00:00'], column_types={'value': 'DATE'})
    assert ready.empty and len(quarantine) == 1


@pytest.mark.parametrize('values,kind', [
    (['2024-01-01', '2024-02-29'], 'DATE'),
    (['2024-01-01'] * 9 + ['2024-01-01T12:00:00'], 'DATETIME'),
    (['2024-01-01T12:00:00+02:00'], 'TIMESTAMP'),
    (['2024-01-01T12:00:00+02:00', '2024-01-01T12:00:00'], 'STRING'),
])
def test_iso_date_semantics(values, kind):
    _, ready, quarantine, report = clean(values)
    assert report['value'] == kind and quarantine.empty
    assert len(ready) == len(values)


def test_metadata_names_never_replace_original_values():
    raw = pd.DataFrame({'value': ['bad'], 'quarantine_reason': ['original'],
                        'source_position': ['original position'], 'original_index': ['old index']})
    _, _, quarantine, _ = clean_generic_dataframe(raw, column_types={'value': 'INTEGER'})
    assert quarantine['quarantine_reason'].tolist() == ['original']
    assert quarantine['source_position'].tolist() == ['original position']
    assert quarantine[quarantine.attrs['metadata_columns']['source_position']].tolist() == [0]


@given(st.lists(st.text(max_size=350), min_size=0, max_size=20))
def test_names_property(headers):
    from src_lib.clean_da_mess import unique_column_names
    import re
    names = unique_column_names(headers)
    assert len(names) == len(headers) == len(set(names))
    assert all(re.fullmatch(r'[a-z_][a-z_0-9]{0,299}', name) for name in names)
    assert unique_column_names(names) == names


def test_quarantine_partition_with_mixed_index_and_multiple_errors():
    raw = pd.DataFrame({'a': ['2', 'oops', '3'], 'b': ['bad', 'bad', 'true']}, index=[1, 'a', 1])
    _, ready, quarantine, _ = clean_generic_dataframe(raw, column_types={'a': 'INTEGER', 'b': 'BOOLEAN'})
    assert len(ready) + len(quarantine) == len(raw)
    assert ready['a'].tolist() == [3]
    assert quarantine['a'].tolist() == ['2', 'oops']
    assert "Column 'a'" in quarantine.iloc[1][quarantine.attrs['metadata_columns']['quarantine_reason']]


def test_locale_never_reinterprets_native_numeric_cells():
    _, ready, quarantine, report = clean([12.345, '12,345', Decimal('0.000000001'), 123], number_format='eu')
    assert report['value'] == 'NUMERIC'
    assert ready['value'].tolist() == [Decimal('12.345'), Decimal('12.345'), Decimal('0.000000001'), Decimal('123')]
    assert quarantine.empty


def test_header_truncation_stays_stable_at_separator_boundary():
    from src_lib.clean_da_mess import unique_column_names
    names = unique_column_names(['a' * 298 + '__' + 'b'] * 3)
    assert unique_column_names(names) == names
    assert len(set(names)) == 3


def test_zero_with_large_exponent_does_not_expand_export():
    from src_lib.spreadsheet_to_jsonl import dataframe_to_jsonl
    output = dataframe_to_jsonl(pd.DataFrame({'amount': [Decimal('0E-9999999')]}), {'amount': 'NUMERIC'})
    assert output == '{"amount":"0"}\n'


def test_mixed_currencies_never_lose_denomination():
    values = ['$10.25', '€20.50', 'C$30.75']
    _, ready, quarantine, report = clean(values, number_format='us')
    assert ready['value'].tolist() == values
    assert report['value'] == 'STRING' and quarantine.empty
    with pytest.raises(ValueError, match='currenc'):
        clean(values, number_format='us', column_types={'value': 'NUMERIC'})


@pytest.mark.parametrize('values', [['001.0', '002.0'], ['00123', '456']])
def test_leading_zero_formats_preserve_whole_column(values):
    _, ready, _, report = clean(values)
    assert ready['value'].tolist() == values and report['value'] == 'STRING'


def test_nonfinite_and_nested_cells_are_recoverable_rejections():
    values = [float('inf'), Decimal('NaN'), {'a': 1}, 'text', None]
    _, ready, quarantine, _ = clean(values)
    assert ready['value'].tolist() == ['text', None]
    assert len(quarantine) == 3
    assert quarantine.iloc[2]['value'] == {'a': 1}
