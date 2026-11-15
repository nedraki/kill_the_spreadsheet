from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook
from streamlit.testing.v1 import AppTest


APP = str(Path(__file__).parents[1] / 'main.py')


def upload(rows):
    book = Workbook()
    for row in rows:
        book.active.append(row)
    stream = BytesIO()
    book.save(stream)
    stream.name = 'messy.xlsx'
    return stream


def test_app_without_upload():
    app = AppTest.from_file(APP).run()
    assert not app.exception
    assert not app.get('download_button')


def test_app_rules_quarantine_and_invalid_rerun_remove_downloads():
    source = upload([['ID', 'Amount'], ['00123', '10'], ['00456', 'bad']])
    with patch('streamlit.file_uploader', return_value=source):
        app = AppTest.from_file(APP).run()
        assert not app.exception and not app.error
        assert len(app.get('download_button')) == 3
        app.text_area[1].set_value('{"amount":"INTEGER"}').run()
        assert not app.exception and not app.error
        assert len(app.get('download_button')) == 4
        assert any('1 rows were excluded' in message.value for message in app.warning)
        app.text_area[1].set_value('{broken').run()
        assert app.error
        assert not app.get('download_button')


def test_unsafe_new_upload_removes_previous_downloads():
    with patch('streamlit.file_uploader', return_value=upload([['ID'], ['00123']])):
        app = AppTest.from_file(APP).run()
        assert len(app.get('download_button')) == 3
    with patch('streamlit.file_uploader', return_value=upload([['ID'], ['=1+1']])):
        app.run()
        assert app.error and 'A2' in app.error[0].value
        assert not app.get('download_button')


def test_duplicate_headers_display_and_all_rejected_export_disabled():
    with patch('streamlit.file_uploader', return_value=upload([['ID', 'ID'], ['abc', 'def']])):
        app = AppTest.from_file(APP).run()
        assert not app.exception and not app.error
        app.text_area[1].set_value('{"id":"INTEGER"}').run()
        assert not app.exception and not app.error
        assert app.get('download_button')[0].proto.disabled
        assert len(app.get('download_button')) == 4


def test_empty_sheet_and_invalid_type_rules():
    with patch('streamlit.file_uploader', return_value=upload([['ID']])):
        app = AppTest.from_file(APP).run()
        assert not app.exception and not app.error
        assert app.get('download_button')[0].proto.disabled
        assert any('no data rows' in warning.value for warning in app.warning)
        app.text_area[1].set_value('[]').run()
        assert app.error and not app.get('download_button')
