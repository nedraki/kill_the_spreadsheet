import streamlit as st
import pandas as pd
import os # Added for filename manipulation
from src_lib.spreadsheet_to_jsonl import excel_to_jsonl

# --- Page Configuration (Adds a professional touch) ---
st.set_page_config(
    page_title="Excel to JSONL Converter",
    page_icon="🔄",
    layout="wide",
)

# --- Session State Management ---

# Initialize session state for converted data and filename
if 'jsonl_data' not in st.session_state:
    st.session_state.jsonl_data = None
if 'file_name' not in st.session_state:
    st.session_state.file_name = None

# Callback function to clear state when a new file is uploaded
# This ensures old data disappears when the user uploads a new file.
def clear_existing_data():
    st.session_state.jsonl_data = None
    st.session_state.file_name = None

# --- Main App ---

st.title("☠️ Kill the spreadsheet")
st.subheader("Convert Excel to JSONL to facilitate data upload into BigQuery")
st.divider()

# --- Step 1: Upload ---
# We use a container to visually group the upload step.
with st.container(border=True):
    st.subheader("📄Step 1: Upload Your File")
    excel_file = st.file_uploader(
        "Upload an Excel file", 
        type=["xlsx", "xls"], # Allow both xls and xlsx
        on_change=clear_existing_data # Call the callback on any change
    )

# --- Step 2 & 3: Process, Preview, and Download (Reactive) ---
# This entire block only runs if a file has been uploaded.
if excel_file is not None:
    
    try:
        # Show a spinner while processing
        with st.spinner(f"Processing {excel_file.name}..."):
            
            # 1. Read file for preview
            df_preview = pd.read_excel(excel_file)
            
            # 2. Reset file pointer to be read again by your function
            # (Important! pd.read_excel moves the 'cursor' to the end)
            excel_file.seek(0) 
            
            # 3. Run conversion (This happens automatically)
            st.session_state.jsonl_data = excel_to_jsonl(excel_file)
            
            # 4. Store filename
            base_name = os.path.splitext(excel_file.name)[0]
            st.session_state.file_name = base_name

        # Show success outside the spinner
        st.success("✅ File processed successfully!")

        # --- Show Preview ---
        with st.container(border=True):
            st.subheader("💡 Step 2: Preview Data")
            st.write("Showing the first 5 rows of your file:")
            st.dataframe(df_preview.head())

        # --- Show Download Button ---
        # This now appears automatically because st.session_state.jsonl_data is set
        with st.container(border=True):
            st.subheader("🚀 Step 3: Download Your File")
            st.download_button(
                label=f"Download {st.session_state.file_name}.jsonl",
                data=st.session_state.jsonl_data,
                file_name=f'{st.session_state.file_name}.jsonl',
                mime='application/jsonl',
                use_container_width=True # Makes the button more prominent
            )

    except Exception as e:
        st.error(f"An error occurred during processing: {e}")
        st.warning("Please ensure you uploaded a valid Excel file.")
        # Clear state on error
        clear_existing_data()