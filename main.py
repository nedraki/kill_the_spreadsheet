import streamlit as st
import pandas as pd
import os
import json
from src_lib.spreadsheet_to_jsonl import dataframe_to_jsonl, bigquery_schema
from src_lib.clean_da_mess import clean_generic_dataframe


# --- Page Configuration (Adds a professional touch) ---
st.set_page_config(
    page_title="Excel to JSONL Converter",
    page_icon="🔄",
    layout="wide",
)

# --- Session State Management ---

# Initialize session state for converted data and filename
if "jsonl_data" not in st.session_state:
    st.session_state.jsonl_data = None
if "file_name" not in st.session_state:
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
        type=["xlsx", "xls"],  # Allow both xls and xlsx
        on_change=clear_existing_data,  # Call the callback on any change
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



            # 4. Store filename
            base_name = os.path.splitext(excel_file.name)[0]
            st.session_state.file_name = base_name

        # Show success outside the spinner
        st.success("✅ File processed successfully!")

        # --- Show Preview ---
        with st.container(border=True):
            st.subheader("💡 Step 2: Preview raw data")
            st.write("Showing the first 5 rows of your file:")
            st.dataframe(df_preview.head())
            st.subheader("🚀 Step 3: Clean data & data validations")
            raw_df = pd.read_excel(excel_file)
            threshold = st.slider(
                "Type Inference Threshold",
                min_value=0.6,
                max_value=1.0,
                value=0.9,
                help=f"A column acquires a datatype if the software can sucessfully parse a ratio of all the values in column. Columns with significant data quality errors will tend to be STRING type if you set a high ratio",
            )
            
            # 3. Run conversion (This happens automatically)
            (
                df_comparison,
                df_load_ready,
                df_quarantine,
                type_report,
            ) = clean_generic_dataframe(raw_df, TYPE_INFERENCE_THRESHOLD=threshold)
            
            # JSONL data session state
            # TO DO: Integrate regex into clean da mess to avoid special characters (using excel to json temporarily)
            st.session_state.jsonl_data = dataframe_to_jsonl(df_load_ready, type_report)

            st.success("Showing the first 5 rows of cleaned data:")
            st.write(df_load_ready.head())
            st.warning("Data quality issues found on these rows:")
            st.write(df_quarantine.head())
            st.success("Data types inferred:")
            st.write(type_report)

        # --- Show Download Button ---
        # This now appears automatically because st.session_state.jsonl_data is set
        with st.container(border=True):
            st.subheader("🚀 Step 3: Download Your File")
            st.info("Load the JSONL with the matching schema below; disable BigQuery schema autodetection.")
            st.download_button(
                label="Download BigQuery schema",
                data=json.dumps(bigquery_schema(type_report), indent=2),
                file_name=f"{st.session_state.file_name}.schema.json",
                mime="application/json",
            )
            st.download_button(
                label=f"Download {st.session_state.file_name}.jsonl",
                data=st.session_state.jsonl_data,
                file_name=f"{st.session_state.file_name}.jsonl",
                mime="application/jsonl",
                use_container_width=True,  # Makes the button more prominent
            )

    except Exception as e:
        st.error(f"An error occurred during processing: {e}")
        st.warning("Please ensure you uploaded a valid Excel file.")
        # Clear state on error
        clear_existing_data()