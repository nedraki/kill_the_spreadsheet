"""Reviewable Excel cleaning: every download is rebuilt from current inputs."""
import json
from pathlib import Path

import streamlit as st

from src_lib.clean_da_mess import clean_generic_dataframe, unique_column_names
from src_lib.excel_reader import ExcelWorkbook
from src_lib.spreadsheet_to_jsonl import bigquery_schema, dataframe_to_jsonl, quarantine_to_jsonl

st.set_page_config(page_title='Excel to BigQuery', page_icon='🔄', layout='wide')
st.title('☠️ Kill the spreadsheet')
st.write('Clean an Excel table with deterministic rules, review the changes, and export for BigQuery.')
st.caption('Text is preserved unless a rule can parse it safely. No deduplication, filling missing values, or automatic business corrections.')


def preview(frame):
    """Display duplicate headers and mixed exact values without Arrow coercion."""
    result = frame.head(20).copy()
    result.columns = [f'{pos + 1}: {name}' for pos, name in enumerate(result.columns)]
    return result.map(lambda value: None if value is None else str(value))


upload = st.file_uploader('Upload an Excel workbook (.xlsx, up to 10 MiB)', type=['xlsx'])
st.caption('For legacy .xls files, save as .xlsx first. Formula, error and merged cells need to be resolved before export.')
if upload is not None:
    try:
        workbook = ExcelWorkbook(upload)
        sheet = st.selectbox('Worksheet', workbook.sheet_names)
        header_row = int(st.number_input('Header row (Excel row number)', min_value=1, value=1, step=1))
        raw = workbook.read_sheet(sheet, header_row)
        st.subheader('1. Review source data')
        st.dataframe(preview(raw))
        names = unique_column_names(raw.columns)
        st.write('Column mapping (source order → export name)')
        st.dataframe([{'position': pos + 1, 'original': str(original), 'export': name}
                      for pos, (original, name) in enumerate(zip(raw.columns, names))])

        st.subheader('2. Choose cleaning rules')
        threshold = st.slider('Type inference threshold', min_value=0.6, max_value=1.0, value=1.0,
                              help='A lower threshold allows a type when some cells fail. Failed rows go only to the rejection file.')
        number_format = st.selectbox('Number format', ['plain', 'eu', 'us'],
                                     format_func=lambda option: {'plain': 'Conservative (no grouping or currency conversion)',
                                                                 'eu': 'European: 1.234,56', 'us': 'US: 1,234.56'}[option])
        date_choice = st.selectbox('Date format', ['ISO only', 'DD/MM/YYYY', 'MM/DD/YYYY'])
        date_format = {'ISO only': None, 'DD/MM/YYYY': '%d/%m/%Y', 'MM/DD/YYYY': '%m/%d/%Y'}[date_choice]
        null_text = st.text_area('Treat these text values as null (one per line)', value='',
                                 help='Optional and case-insensitive. NA, pending, unknown and other literals are preserved by default.')
        rules_text = st.text_area('Column types (JSON)', value='{}',
                                  help='Use export names, for example {"customer_id":"STRING", "amount":"NUMERIC"}. Types: STRING, BOOLEAN, INTEGER, NUMERIC, DATE, DATETIME, TIMESTAMP.')
        column_types = json.loads(rules_text)
        if not isinstance(column_types, dict):
            raise ValueError('Column types must be a JSON object')
        null_values = null_text.splitlines() if null_text else []
        comparison, ready, quarantine, report = clean_generic_dataframe(
            raw, TYPE_INFERENCE_THRESHOLD=threshold, column_types=column_types,
            number_format=number_format, date_format=date_format, null_values=null_values)
        # Validate all artifacts before rendering any download button.
        jsonl = dataframe_to_jsonl(ready, report)
        schema = bigquery_schema(report)
        rejected = quarantine_to_jsonl(quarantine)
        manifest = {
            'source_file': upload.name, 'sheet': sheet, 'header_row': header_row,
            'input_rows': len(raw), 'accepted_rows': len(ready), 'rejected_rows': len(quarantine),
            'accepted_excel_rows': ready.index.tolist(),
            'column_mapping': ready.attrs['column_mapping'], 'schema': schema,
            'rules': {'threshold': threshold, 'number_format': number_format,
                      'date_format': date_format, 'null_values': null_values, 'column_types': column_types},
        }
        st.subheader('3. Review the result')
        st.write(f'{len(raw)} source rows = {len(ready)} accepted + {len(quarantine)} rejected')
        st.dataframe(preview(ready))
        st.write('Export schema')
        st.dataframe(schema)
        with st.expander('Original and cleaned values side by side'):
            st.dataframe(preview(comparison))
        if len(quarantine):
            st.warning(f'{len(quarantine)} rows were excluded from the main export. Download and resolve the rejected rows.')
            st.dataframe(preview(quarantine))
        else:
            st.success('No rejected rows under the selected rules. Review the schema and preview before loading.')
        if raw.empty:
            st.warning('This table has headers but no data rows.')
        st.subheader('4. Download for BigQuery')
        st.info('Load the JSONL with its matching schema and disable schema autodetection. This preserves text identifiers and exact numbers.')
        base = f'{Path(upload.name).stem}_{sheet}'
        st.download_button('Download accepted JSONL', jsonl, file_name=f'{base}.jsonl',
                           mime='application/x-ndjson', disabled=ready.empty)
        st.download_button('Download BigQuery schema', json.dumps(schema, indent=2),
                           file_name=f'{base}.schema.json', mime='application/json')
        st.download_button('Download cleaning report', json.dumps(manifest, indent=2, ensure_ascii=False),
                           file_name=f'{base}.report.json', mime='application/json')
        if len(quarantine):
            st.download_button('Download rejected rows', rejected, file_name=f'{base}.rejected.jsonl',
                               mime='application/x-ndjson')
    except Exception as exc:
        st.error(f'Cannot export this workbook: {exc}')
        st.caption('Correct the source or the selected rules, then try again.')
