"""Read XLSX cell values without pandas' implicit null/type/header conversions."""
from datetime import date, datetime
from io import BytesIO
import numbers
from pathlib import Path
import re
from zipfile import BadZipFile, ZipFile

from openpyxl import load_workbook
import pandas as pd

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 25 * 1024 * 1024
MAX_CELLS = 250_000


class ExcelWorkbook:
    def __init__(self, source):
        if isinstance(source, (str, Path)):
            with open(source, 'rb') as stream:
                data = stream.read(MAX_UPLOAD_BYTES + 1)
        elif hasattr(source, 'read'):
            # Repeated UI runs must read the same bytes and leave caller position intact.
            position = source.tell()
            try:
                source.seek(0)
                data = source.read(MAX_UPLOAD_BYTES + 1)
            finally:
                source.seek(position)
        else:
            raise TypeError('Expected an XLSX path or seekable binary stream')
        if not isinstance(data, bytes):
            raise TypeError('Workbook must be opened in binary mode')
        if len(data) > MAX_UPLOAD_BYTES:
            raise ValueError('Workbook exceeds the 10 MiB upload limit')
        try:
            with ZipFile(BytesIO(data)) as archive:
                if sum(item.file_size for item in archive.infolist()) > MAX_UNCOMPRESSED_BYTES:
                    raise ValueError('Workbook exceeds the 25 MiB expanded size limit')
            self.book = load_workbook(BytesIO(data), data_only=False, keep_links=False)
        except (BadZipFile, KeyError, OSError) as exc:
            raise ValueError('Invalid XLSX workbook. Save legacy .xls files as .xlsx first.') from exc

    @property
    def sheet_names(self):
        return self.book.sheetnames

    def read_sheet(self, sheet_name=None, header_row=1):
        sheet_name = self.sheet_names[0] if sheet_name is None else sheet_name
        if sheet_name not in self.sheet_names:
            raise ValueError(f'Unknown worksheet: {sheet_name}')
        sheet = self.book[sheet_name]
        if isinstance(header_row, bool) or not isinstance(header_row, int) or not 1 <= header_row <= sheet.max_row:
            raise ValueError('Header row must be an existing Excel row (starting at 1)')
        if sheet.max_row * sheet.max_column > MAX_CELLS:
            raise ValueError(f'Worksheet exceeds the {MAX_CELLS:,} cell limit, including formatted cells')
        merged = [str(area) for area in sheet.merged_cells.ranges if area.max_row >= header_row]
        if merged:
            raise ValueError(f'Unmerge cells in the selected table first: {", ".join(merged[:10])}')
        problems, rows = [], []
        for cells in sheet.iter_rows(min_row=header_row):
            row = []
            for cell in cells:
                value = cell.value
                if cell.data_type in {'f', 'e'}:
                    problems.append(f'{cell.coordinate}: formula or Excel error; replace with verified values')
                elif (isinstance(value, (date, datetime)) and self.book.epoch.year == 1899
                      and (value.date() if isinstance(value, datetime) else value) == date(1900, 2, 28)):
                    # Excel serials 59 and the fictitious leap day 60 decode identically.
                    problems.append(f'{cell.coordinate}: ambiguous Excel 1900 leap day; provide verified ISO date text')
                elif isinstance(value, numbers.Real) and not isinstance(value, bool):
                    if abs(value) >= 10**15:
                        problems.append(f'{cell.coordinate}: large Excel number; provide exact source text')
                    if re.search(r'(?<![.0])0{2,}', cell.number_format):
                        problems.append(f'{cell.coordinate}: zero-padded display; store identifiers as text')
                row.append(value)
            rows.append(row)
        if problems:
            raise ValueError(f'Unsafe cells in {sheet_name}: ' + '; '.join(problems[:20])
                             + (f'; and {len(problems) - 20} more' if len(problems) > 20 else ''))
        if not rows or all(value is None for value in rows[0]):
            raise ValueError('The selected header row is empty')
        frame = pd.DataFrame(rows[1:], columns=rows[0], dtype=object)
        frame.index = pd.Index(range(header_row + 1, header_row + 1 + len(frame)), name='excel_row')
        frame.attrs['source_sheet'] = sheet_name
        frame.attrs['header_row'] = header_row
        return frame


def read_excel(input_data, *, sheet_name=None, header_row=1):
    return ExcelWorkbook(input_data).read_sheet(sheet_name, header_row)
