from io import BytesIO
import json

from openpyxl import Workbook
import pytest

from src_lib.spreadsheet_to_jsonl import excel_to_jsonl


def workbook_bytes(rows, *, sheet='Data'):
    book = Workbook()
    book.active.title = sheet
    for row in rows:
        book.active.append(row)
    output = BytesIO()
    book.save(output)
    output.seek(0)
    return output


@pytest.mark.parametrize('value', ['=1+1', '#DIV/0!'])
def test_formulas_and_excel_errors_are_not_erased(value):
    source = workbook_bytes([['value', 'other'], [value, 'present']])
    with pytest.raises(ValueError, match='A2'):
        excel_to_jsonl(source)


def test_duplicate_excel_headers_have_positional_mapping():
    source = workbook_bytes([['Name', 'Name'], ['first', 'second']])
    assert json.loads(excel_to_jsonl(source)) == {'name': 'first', 'name_2': 'second'}


def test_large_numeric_excel_identifiers_require_source_text():
    source = workbook_bytes([['id'], [1234567890123456]])
    with pytest.raises(ValueError, match='A2'):
        excel_to_jsonl(source)


from src_lib.excel_reader import ExcelWorkbook, read_excel
from src_lib.clean_da_mess import clean_generic_dataframe
from src_lib.spreadsheet_to_jsonl import dataframe_to_jsonl, quarantine_to_jsonl


def test_literal_strings_blank_cells_duplicate_headers_and_cursor():
    source = workbook_bytes([['Code', 'Code', None, 'Status'],
                             ['00123', 'NA', None, 'NULL'],
                             [None, None, None, None],
                             ['00456', 'N/A', None, 'pending']])
    source.seek(10)
    frame = read_excel(source)
    assert source.tell() == 10
    assert frame.shape == (3, 4)
    assert frame.columns.tolist() == ['Code', 'Code', None, 'Status']
    assert frame.iloc[0].tolist() == ['00123', 'NA', None, 'NULL']
    assert frame.iloc[1].tolist() == [None] * 4
    result = [json.loads(line) for line in excel_to_jsonl(source).splitlines()]
    assert result[0] == {'code': '00123', 'code_2': 'NA', 'unnamed_col': None, 'status': 'NULL'}
    assert len(result) == 3


def test_sheet_selection_header_and_complete_roundtrip():
    book = Workbook()
    book.active.title = 'Instructions'
    book.active.append(['=1+1'])  # Unselected sheet is not a table.
    table = book.create_sheet('Transactions')
    table.append(['Monthly report'])
    table.merge_cells('A1:C1')  # Preamble outside the table is allowed.
    table.append(['Account ID', 'Amount (€)', 'Date', 'Status'])
    table.append(['00123', '1.234,56', '01/02/2024', 'pending'])
    table.append(['00456', 'bad', '02/02/2024', 'unknown'])
    table.append(['00789', '0,000000001', '03/02/2024', 'NA'])
    output = BytesIO()
    book.save(output)
    raw = read_excel(output, sheet_name='Transactions', header_row=2)
    _, ready, quarantine, report = clean_generic_dataframe(raw, number_format='eu',
        date_format='%d/%m/%Y', column_types={'amount_eur': 'NUMERIC', 'date': 'DATE'})
    assert len(raw) == len(ready) + len(quarantine) == 3
    assert ready.index.tolist() == [3, 5]
    records = [json.loads(line) for line in dataframe_to_jsonl(ready, report).splitlines()]
    assert records == [
        {'account_id': '00123', 'amount_eur': '1234.56', 'date': '2024-02-01', 'status': 'pending'},
        {'account_id': '00789', 'amount_eur': '0.000000001', 'date': '2024-02-03', 'status': 'NA'}]
    rejected = json.loads(quarantine_to_jsonl(quarantine))
    assert rejected['original_index'] == '4'
    assert rejected['cells'][1]['value'] == 'bad'


def test_merged_table_cells_block_export():
    book = Workbook()
    book.active.append(['A', 'B'])
    book.active.append(['merged', None])
    book.active.merge_cells('A2:B2')
    source = BytesIO()
    book.save(source)
    with pytest.raises(ValueError, match='A2:B2'):
        read_excel(source)


def test_zero_padded_display_is_not_exported_as_short_number():
    book = Workbook()
    book.active.append(['ID'])
    book.active.append([123])
    book.active['A2'].number_format = '00000'
    source = BytesIO()
    book.save(source)
    with pytest.raises(ValueError, match='A2'):
        read_excel(source)


@pytest.mark.parametrize('source', [b'not excel', b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'])
def test_invalid_and_legacy_files_raise_clear_error(source):
    with pytest.raises(ValueError, match='XLSX'):
        read_excel(BytesIO(source))


def test_empty_and_header_only_tables():
    with pytest.raises(ValueError, match='empty'):
        read_excel(workbook_bytes([]))
    raw = read_excel(workbook_bytes([['a', 'b']]))
    assert raw.shape == (0, 2)
    assert excel_to_jsonl(workbook_bytes([['a', 'b']])) == ''


def test_bad_sheet_header_and_size_limits(monkeypatch):
    book = ExcelWorkbook(workbook_bytes([['a'], ['text']]))
    with pytest.raises(ValueError, match='worksheet'):
        book.read_sheet('missing')
    with pytest.raises(ValueError, match='Header'):
        book.read_sheet(header_row=3)
    monkeypatch.setattr('src_lib.excel_reader.MAX_CELLS', 1)
    with pytest.raises(ValueError, match='cell limit'):
        book.read_sheet()
    monkeypatch.setattr('src_lib.excel_reader.MAX_UPLOAD_BYTES', 1)
    with pytest.raises(ValueError, match='upload limit'):
        ExcelWorkbook(workbook_bytes([['a']]))


def test_expanded_size_limit(monkeypatch):
    monkeypatch.setattr('src_lib.excel_reader.MAX_UNCOMPRESSED_BYTES', 1)
    with pytest.raises(ValueError, match='expanded size'):
        ExcelWorkbook(workbook_bytes([['a']]))


def test_path_input(tmp_path):
    path = tmp_path / 'source.xlsx'
    path.write_bytes(workbook_bytes([['ID'], ['00123']]).getvalue())
    assert json.loads(excel_to_jsonl(path)) == {'id': '00123'}


def test_1904_calendar_and_hidden_rows_are_respected():
    from datetime import datetime
    from openpyxl.utils.datetime import CALENDAR_MAC_1904
    book = Workbook()
    book.epoch = CALENDAR_MAC_1904
    book.active.append(['date'])
    book.active.append([datetime(2024, 1, 1)])
    book.active.row_dimensions[2].hidden = True
    source = BytesIO()
    book.save(source)
    assert json.loads(excel_to_jsonl(source)) == {'date': '2024-01-01'}


def test_1900_fictitious_leap_day_is_not_aliased_to_february_28():
    book = Workbook()
    book.active.append(['date'])
    book.active.append([60])
    book.active['A2'].number_format = 'yyyy-mm-dd'
    source = BytesIO()
    book.save(source)
    with pytest.raises(ValueError, match='A2'):
        read_excel(source)
