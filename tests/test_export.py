from datetime import date, datetime, timezone
from decimal import Decimal
from io import BytesIO
import json

import pandas as pd
import pytest

from src_lib.spreadsheet_to_jsonl import excel_to_jsonl


def test_converter_does_not_mutate_input():
    frame = pd.DataFrame({'Original Name': ['hello']})
    snapshot = frame.copy(deep=True)
    assert json.loads(excel_to_jsonl(frame)) == {'original_name': 'hello'}
    pd.testing.assert_frame_equal(frame, snapshot)


def test_converter_preserves_high_precision_as_string():
    frame = pd.DataFrame({'number': [Decimal('0.123456789123456789')]})
    assert json.loads(excel_to_jsonl(frame))['number'] == '0.123456789123456789'


def test_converter_supports_unnamed_stream():
    stream = BytesIO()
    pd.DataFrame({'A B': ['hello']}).to_excel(stream, index=False)
    stream.seek(0)
    assert json.loads(excel_to_jsonl(stream)) == {'a_b': 'hello'}


def test_converter_raises_actionable_error():
    with pytest.raises(TypeError):
        excel_to_jsonl(123)


from src_lib.spreadsheet_to_jsonl import bigquery_schema, dataframe_to_jsonl, quarantine_to_jsonl
from src_lib.clean_da_mess import clean_generic_dataframe


def test_exact_bigquery_values_and_matching_schema():
    raw = pd.DataFrame({'id': ['9007199254740993', None],
                        'amount': ['123.123456789', '0.000000001'],
                        'label': ['00123', 'NA']}, dtype=object)
    _, ready, _, report = clean_generic_dataframe(raw)
    lines = [json.loads(line) for line in dataframe_to_jsonl(ready, report).splitlines()]
    assert lines == [{'id': '9007199254740993', 'amount': '123.123456789', 'label': '00123'},
                     {'id': None, 'amount': '0.000000001', 'label': 'NA'}]
    assert bigquery_schema(report) == [
        {'name': 'id', 'type': 'INTEGER', 'mode': 'NULLABLE'},
        {'name': 'amount', 'type': 'NUMERIC', 'mode': 'NULLABLE'},
        {'name': 'label', 'type': 'STRING', 'mode': 'NULLABLE'}]


def test_unicode_newlines_boolean_and_date():
    raw = pd.DataFrame({'text': ['héllo\n"世界"'], 'boolean': [True],
                        'date': [date(2024, 1, 2)],
                        'timestamp': [datetime(2024, 1, 2, tzinfo=timezone.utc)]})
    _, ready, _, report = clean_generic_dataframe(raw)
    output = dataframe_to_jsonl(ready, report)
    assert len(output.splitlines()) == 1
    assert json.loads(output) == {'text': 'héllo\n"世界"', 'boolean': True,
                                 'date': '2024-01-02', 'timestamp': '2024-01-02T00:00:00+00:00'}


@pytest.mark.parametrize('value,kind', [(float('inf'), 'NUMERIC'), (Decimal('NaN'), 'NUMERIC'),
                                      (2**63, 'INTEGER'), (Decimal('0.0000000001'), 'NUMERIC'),
                                      (pd.Timestamp('2024-01-01T00:00:00.000000001'), 'DATETIME')])
def test_invalid_export_rejected(value, kind):
    with pytest.raises(ValueError):
        dataframe_to_jsonl(pd.DataFrame({'value': [value]}, dtype=object), {'value': kind})


def test_schema_and_columns_must_agree():
    with pytest.raises(ValueError):
        dataframe_to_jsonl(pd.DataFrame({'a': ['text']}), {'b': 'STRING'})
    with pytest.raises(ValueError):
        bigquery_schema({'a': 'EMPTY'})


def test_empty_export_is_empty_string():
    assert dataframe_to_jsonl(pd.DataFrame(columns=['a']), {'a': 'STRING'}) == ''


def test_quarantine_export_preserves_duplicate_source_headers():
    raw = pd.DataFrame([['bad', 'original', Decimal('0.123456789123456789')]],
                       columns=['x', 'x', 'quarantine_reason'])
    _, _, quarantine, _ = clean_generic_dataframe(raw, column_types={'x': 'INTEGER'})
    record = json.loads(quarantine_to_jsonl(quarantine))
    assert record['source_position'] == 0
    assert [cell['value'] for cell in record['cells']] == ['bad', 'original', '0.123456789123456789']
    assert [cell['original'] for cell in record['cells']] == ['x', 'x', 'quarantine_reason']


def test_convenience_converter_does_not_hide_rejections():
    with pytest.raises(ValueError, match='quarantine'):
        excel_to_jsonl(pd.DataFrame({'a': ['10'] * 9 + ['broken']}))
