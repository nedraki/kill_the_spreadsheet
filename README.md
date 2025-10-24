# Excel to JSONL Converter

A simple and efficient web tool built with Streamlit to convert Excel files into the JSONL (JSON Lines) format, making it easy to upload structured data into systems like Google BigQuery.

The tool performs automated cleaning of column headers to ensure they are compatible with database and data warehousing best practices.

## What it Does

This tool provides a user-friendly interface to:

*   **Upload Excel Files**: Supports both `.xlsx` and `.xls` formats.
*   **Automated Column Cleaning**: Automatically cleans column names to make them BigQuery-compatible by:
    *   Converting all characters to lowercase.
    *   Replacing spaces with underscores (`_`).
    *   Removing special characters (e.g., `.` `(` `)` `+` `/`).
*   **Instant Conversion**: Converts the spreadsheet data into a JSONL string, where each row from the Excel file becomes a separate JSON object on a new line.
*   **Data Preview**: Shows a preview of the first few rows of the original uploaded data.
*   **One-Click Download**: Allows the user to download the final, clean `.jsonl` file.

## Future Developments

We are actively working on expanding the capabilities of this tool. Planned features include:

*   **CSV to JSONL**: Adding support for `.csv` files as an input source.
*   **Spreadsheet to DuckDB**: A powerful feature to directly load spreadsheet data into an in-memory or file-based DuckDB database, enabling fast SQL-based analysis directly in the browser.

## Blog Posts / Tutorials

Stay tuned...
---

*Spreadsheets are cool but modern times demand better data practices*
