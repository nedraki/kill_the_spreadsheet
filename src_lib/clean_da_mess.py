import pandas as pd
import numpy as np
import janitor
import re
from typing import Tuple, Dict, Any
import dateparser  # <-- Added dateparser import

# --- Constants for Type Inference ---

# Values to be universally treated as "missing" or "not applicable"
# We do this BEFORE type inference.
JUNK_VALUES = {
    "na",
    "n/a",
    "#na",
    "null",
    "none",
    "pending",
    "unknown",
    "undefined",
    "--",
    "...",
    "",
}

# Values to be interpreted as BOOLEAN True
TRUE_VALUES = {"true", "1", "yes", "y", "t", "active", "on"}

# Values to be interpreted as BOOLEAN False
FALSE_VALUES = {"false", "0", "no", "n", "f", "inactive", "off"}

# --- NEW: Define currency symbols to replace ---
# NOTE: Multi-character symbols like 'C$' must come BEFORE

# Single-character symbols like '$' to be replaced correctly.
CURRENCY_MAP = {
    'C$': '_cad_',
    'A$': '_aud_',
    '€': '_eur_',
    '$': '_usd_',
    '£': 'gbp',
    '¥': 'jpy',
    '₹': 'inr',
    '₩': 'krw',
    '₽': 'rub',
    # --- Add any other symbols you need here ---
}

def clean_bigquery_column(col_name):
    """
    Cleans a string to make it a valid BigQuery column name,
    replacing common currency symbols with their 3-letter codes.
    """
    
    cleaned = str(col_name)

    # 1. NEW: Replace currency symbols first
    for symbol, code in CURRENCY_MAP.items():
        cleaned = cleaned.replace(symbol, code)
    
    # 2. Replace remaining invalid characters with an underscore
    cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", cleaned)
    
    # 3. Remove leading/trailing underscores
    cleaned = cleaned.strip("_")
    
    # 4. Convert to lowercase
    cleaned = cleaned.lower()
    
    # 5. Handle rule: Must start with a letter or underscore
    if re.match(r"^[0-9]", cleaned):
        cleaned = "_" + cleaned
        
    # 6. Handle empty strings
    if not cleaned:
        cleaned = "unnamed_col"
        
    # 7. Handle max length (300 chars)
    return cleaned[:300]


def clean_generic_dataframe(
    df_raw: pd.DataFrame, TYPE_INFERENCE_THRESHOLD=0.90
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict[str, str]]:
    """
    Cleans a generic, messy DataFrame by inferring types, coercing data,
    and quarantining rows that fail to parse.

    Args:
        df_raw (pd.DataFrame): The raw, messy pandas DataFrame (e.g., from pd.read_excel).
        TYPE_INFERENCE_THRESHOLD (float): The ratio of values in a column that must
            successfully parse to a given type for the entire column to be
            coerced to that type.
            # Heuristic: If > this % of non-null data parses, we'll assign the type
Defaults to 0.90.

    Returns:
        Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict[str, str]]:
            A tuple containing four items:
            1. df_comparison: A DataFrame showing the original data side-by-side
               with the new '_clean' columns for comparison.
            2. df_load_ready: A DataFrame containing *only* the cleaned and
               coerced data, ready for loading into a database. Column names
               are sanitized.
            3. df_quarantine: A DataFrame containing the *original* rows that
               had at least one value that failed parsing, plus a detailed
               'quarantine_reason' column.
            4. type_report: A dictionary mapping original column names to
               their inferred data type (e.g., {'user_id': 'INTEGER'}).
    """
    if not isinstance(df_raw, pd.DataFrame):
        raise ValueError("Input must be a pandas DataFrame")

    # --- 0. Pre-processing ---

    # 1. Use pyjanitor to clean column names (e.g., "Total Spend ($)" -> "total_spend_dollar")
    try:
        df = df_raw.copy().clean_names()
        df.columns= [clean_bigquery_column(col) for col in df.columns]
    except:
        # Handle potential edge cases in clean_names, though rare
        df.columns= [clean_bigquery_column(col) for col in df.columns]

    # 2. Drop columns and rows that are *entirely* empty
    df = df.dropna(how="all", axis=1)  # Drop empty cols
    df = df.dropna(how="all", axis=0)  # Drop empty rows

    # Store original indices to reference the raw file
    original_indices = df.index
    df = df.reset_index(drop=True)  # Use a clean 0-based index for looping

    # Helper function for dateparser
    def _parse_date_robust(date_str):
        """
        Robustly parses a date string using the `dateparser` library.

        Handles NaNs, converts input to string, and returns pd.NaT on any error.

        Args:
            date_str (Any): The value to parse as a date.

        Returns:
            datetime or pd.NaT: The parsed datetime object or NaT if parsing fails.
        """
        if pd.isna(date_str):
            return pd.NaT
        try:
            # dateparser is very flexible but can be slow
            return dateparser.parse(str(date_str))
        except (TypeError, OverflowError, ValueError):  # Catch more errors
            # Handle potential errors from dateparser
            return pd.NaT

    bad_rows_log = []
    clean_column_map = {}
    type_report = {}

    # --- 1. The "Gauntlet": Iterate over each column ---
    for col_name in df.columns:
        if col_name.endswith("_clean"):  # Skip columns we may have already added
            continue

        series = df[col_name]

        # 2. Standardize Junk Values
        # Convert all to string, strip, lower, and replace JUNK_VALUES with np.nan
        series_str_lower = series.astype(str).str.strip().str.lower()
        series_std = series.where(~series_str_lower.isin(JUNK_VALUES))

        original_non_null_count = series_std.notna().sum()

        # If column is now empty, skip it
        if original_non_null_count == 0:
            type_report[col_name] = "EMPTY"
            clean_column_map[f"{col_name}_clean"] = series_std
            continue

        inferred_type = "STRING"  # Default
        clean_series = series_std  # Default

        # --- 3. Heuristics: Try to infer type ---

        # --- Check 1: BOOLEAN ---
        # If all unique non-null values are in our boolean sets
        unique_vals = set(series_std.dropna().astype(str).str.strip().str.lower())
        if unique_vals.issubset(TRUE_VALUES.union(FALSE_VALUES)):
            inferred_type = "BOOLEAN"
            bool_map = {v: True for v in TRUE_VALUES} | {v: False for v in FALSE_VALUES}
            clean_series = series_std.astype(str).str.strip().str.lower().map(bool_map)

        else:
            # --- Check 2: NUMERIC (INTEGER / FLOAT) ---

            # Pre-clean numeric strings: remove $, €, commas, spaces
            # And handle accounting format: (100.50) -> -100.50
            series_numeric_str = (
                series_std.astype(str)
                .str.replace(r"[$,€\s,]", "", regex=True)
                .str.replace(r"^\((.*)\)$", r"-\1", regex=True)  # (100) -> -100
            )

            # Try to coerce to number
            coerced_numeric = pd.to_numeric(series_numeric_str, errors="coerce")
            success_ratio = coerced_numeric.notna().sum() / original_non_null_count

            if success_ratio >= TYPE_INFERENCE_THRESHOLD:
                # It's numeric. Is it INT or FLOAT?
                # Check if all non-null coerced values are whole numbers
                if (coerced_numeric.dropna() % 1 == 0).all():
                    inferred_type = "INTEGER"
                    clean_series = coerced_numeric
                else:
                    inferred_type = "FLOAT"
                    clean_series = coerced_numeric

            else:
                # --- Check 3: DATETIME (using dateparser) ---
                # This is slower, so we do it after numeric
                
                # Exclude obvious non-dates (like long numbers) to speed up parser
                # This is a heuristic: Excel serial dates are 5 digits.
                likely_dates = series_std[
                    series_std.astype(str).str.len() < 30  # Exclude long text
                ]

                # Run heuristic check on likely dates
                coerced_datetime = likely_dates.apply(_parse_date_robust)
                success_ratio = (
                    coerced_datetime.notna().sum() / original_non_null_count
                )

                if success_ratio >= TYPE_INFERENCE_THRESHOLD:
                    inferred_type = "DATETIME"
                    # We must re-run on the *whole* series_std to get the final clean_series
                    clean_series = series_std.apply(_parse_date_robust)

        # --- 4. Store Results & Log Bad Rows ---
        type_report[col_name] = inferred_type
        clean_column_map[f"{col_name}_clean"] = clean_series

        # Find the "bad" rows:
        # Where the standardized original was NOT null,
        # but the new clean version IS null.
        bad_mask = (series_std.notna()) & (clean_series.isna())

        if bad_mask.any():
            failed_indices = df[bad_mask].index
            for idx in failed_indices:
                bad_rows_log.append(
                    {
                        "original_index": original_indices[idx],  # Get index from pre-reset df
                        "quarantined_column": col_name,
                        "original_value": df.iloc[idx][col_name],
                        "reason": f"Failed to parse as {inferred_type}",
                    }
                )

    # --- 5. Assemble Final Outputs ---

    # 1. Create df_comparison (for comparison)
    df_comparison = df.copy()
    # Add all the new clean columns
    for col_name, col_series in clean_column_map.items():
        df_comparison[col_name] = col_series
    
    # Restore original index
    df_comparison.index = original_indices

    # 2. Create df_load_ready (with only clean data, ready for BQ)
    df_load_ready_data = {}
    for col_name in type_report.keys():
        clean_col_key = f"{col_name}_clean"
        if clean_col_key in clean_column_map:
            # Add the clean series under the original sanitized name
            df_load_ready_data[col_name] = clean_column_map[clean_col_key]
        elif col_name in df:
            # Fallback: This column was in type_report (e.g., 'EMPTY' or 'STRING')
            # but had no clean series generated. Use the standardized original.
            df_load_ready_data[col_name] = df[col_name]

    df_load_ready = pd.DataFrame(df_load_ready_data)
    # Restore original index
    df_load_ready.index = original_indices

    # 3. Create df_quarantine
    if not bad_rows_log:
        # No bad rows found!
        df_quarantine = pd.DataFrame(
            columns=["original_index", "quarantine_reason"] + df_raw.columns.tolist()
        )
    else:
        quarantine_report = pd.DataFrame(bad_rows_log)

        # Get all unique bad row indices
        bad_indices = sorted(list(set(quarantine_report["original_index"])))

        # Get the original, unmodified rows from the raw file
        df_quarantine = df_raw.loc[bad_indices].copy()

        # Create a summary of all errors for each row
        reason_summary = (
            quarantine_report.groupby("original_index")
            .apply(
                lambda x: "; ".join(
                    f"Column '{r['quarantined_column']}': "
                    f"Value '{r['original_value']}' "
                    f"({r['reason']})"
                    for i, r in x.iterrows()
                )
            )
            .rename("quarantine_reason")
        )

        # Add the quarantine_reason as a new column
        df_quarantine = df_quarantine.merge(
            reason_summary, left_index=True, right_index=True
        )

    return df_comparison, df_load_ready, df_quarantine, type_report