"""Export builders (Excel, CSV bytes)."""

from io import BytesIO

import pandas as pd


def excel_report(landcover_df=None, villages_df=None):
    """Build a multi-sheet Excel report and return it as bytes."""

    buf = BytesIO()

    with pd.ExcelWriter(buf, engine="openpyxl") as xw:

        if landcover_df is not None and not landcover_df.empty:
            landcover_df.to_excel(xw, sheet_name="Land Cover", index=False)

        if villages_df is not None and not villages_df.empty:
            villages_df.to_excel(xw, sheet_name="Villages", index=False)

    return buf.getvalue()