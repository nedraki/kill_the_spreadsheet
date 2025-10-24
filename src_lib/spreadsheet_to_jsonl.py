import pandas as pd
from typing import Union, IO
import re

def excel_to_jsonl(input_data: Union[str, pd.DataFrame, IO]) -> Union[str, None]:
    
    """    
    Converts an Excel file or DataFrame to a JSONL file, preserving data types.

    Args:
        input_data (Union[str, pd.DataFrame, IO]): The path to the Excel file, a pandas DataFrame,
                                                   or a file-like object (e.g., from Streamlit's file_uploader).
    Returns:
        Union[str, None]: The JSONL data as a string, or None if an error occurred.
    """
    try:
        # Check if input_data is a string (file path) or a file-like object.
        # pd.read_excel can handle both types.
        if isinstance(input_data, str) or hasattr(input_data, 'read'):
            df = pd.read_excel(input_data)
            if isinstance(input_data, str):
                print(f"Reading Excel file from path: '{input_data}'")
            else:
                # It's a file-like object, like streamlit.UploadedFile
                print(f"Reading Excel file from in-memory object: {input_data.name}")
        elif isinstance(input_data, pd.DataFrame):
            df = input_data
            print("Using provided DataFrame")
        else:
            # This case should ideally not be reached if type hints are respected
            raise TypeError("input_data must be a file path, a file-like object, or a pandas DataFrame")

        # Clean column names for BigQuery compatibility
        cleaned_columns = []
        for col in df.columns:
            new_col = col.lower()  # Convert to lowercase
            new_col = new_col.replace(' ', '_')  # Replace spaces with underscores
            new_col = re.sub(r'[^a-zA-Z0-9_]', '', new_col)  # Remove all other invalid characters
            cleaned_columns.append(new_col)
        df.columns = cleaned_columns

        # Convert the DataFrame to JSONL format.
        jsonl_data = df.to_json(orient='records', lines=True, date_format='iso')

        print(f"Successfully converted data to JSONL format.")
        return jsonl_data

    except FileNotFoundError:
        print(f"Error: Excel file not found at '{input_data}'")
        return None
    except Exception as e:
        print(f"An error occurred: {e}")
        return None