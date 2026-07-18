"""Area Report - one PDF assembling all analyses for the buffer.

Sections appear only if their analysis has been run in the app.
Charts are rendered with matplotlib (Agg backend, no display needed).
"""

from datetime import datetime
from io import BytesIO

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

GREEN = colors.HexColor("#2e7d32")
LIGHT = colors.HexColor("#f1f8e9")


def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle(
        "H1x", parent=ss["Heading1"], textColor=GREEN))
    ss.add(ParagraphStyle(
        "H2x", parent=ss["Heading2"], textColor=GREEN))
    return ss


def _table(data, col_widths=None):
    t = Table(data, colWidths=col_widths, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), GREEN),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def _chart_image(fig, width=15 * cm, height=7 * cm):
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return Image(buf, width=width, height=height)


def build_area_report(meta, landcover_df=None, crosscheck=None,
                      crop_insight=None, paddy=None, rain=None,
                      villages_df=None, insights_df=None):
    """Assemble the PDF. Returns bytes."""

    ss = _styles()
    story = []

    # --- Header ---
    from config import APP_NAME, COMPANY, LOGO_PATH

    if LOGO_PATH.exists():
        story.append(Image(str(LOGO_PATH),
                           width=3.5 * cm, height=3.5 * cm,
                           kind="proportional", hAlign="LEFT"))
        story.append(Spacer(1, 4))

    story.append(Paragraph(f"{APP_NAME} - Area Report", ss["H1x"]))
    story.append(Paragraph(
        datetime.now().strftime(f"{COMPANY} | Generated %d %b %Y, %H:%M"),
        ss["Normal"]))
    story.append(Spacer(1, 8))

    header = [
        ["Location", f"{meta['lat']:.6f}, {meta['lon']:.6f}"],
        ["Radius", f"{meta['radius']} km"],
        ["Analysis Year", str(meta['year'])],
    ]
    if meta.get("place"):
        header.insert(0, ["Place", meta["place"]])
    story.append(_table(header, [4 * cm, 11 * cm]))
    story.append(Spacer(1, 12))

    # --- Land cover ---
    if landcover_df is not None and not landcover_df.empty:

        story.append(Paragraph("Land Cover", ss["H2x"]))

        total = landcover_df["Area (acres)"].sum()
        rows = [["Land Cover", "Area (acres)", "Share"]]
        for _, r in landcover_df.iterrows():
            share = (r["Area (acres)"] / total * 100) if total else 0
            rows.append([
                r["Land Cover"],
                f"{r['Area (acres)']:,.0f}",
                f"{share:.1f}%",
            ])
        rows.append(["Total", f"{total:,.0f}", "100%"])
        story.append(_table(rows, [6 * cm, 4.5 * cm, 3 * cm]))

        top = landcover_df.nlargest(6, "Area (acres)")
        fig, ax = plt.subplots(figsize=(7, 3))
        ax.bar(top["Land Cover"], top["Area (acres)"], color="#2e7d32")
        ax.set_ylabel("Acres")
        ax.tick_params(axis="x", rotation=20)
        story.append(Spacer(1, 6))
        story.append(_chart_image(fig))
        story.append(Spacer(1, 12))

    # --- Confidence ---
    if crosscheck:
        story.append(Paragraph("Cropland Confidence", ss["H2x"]))
        story.append(Paragraph(
            f"Two independent datasets agree on "
            f"<b>{crosscheck['confirmed_ac']:,.0f} acres</b> of cropland "
            f"({crosscheck['agreement_pct']}% agreement).", ss["Normal"]))
        story.append(Spacer(1, 12))

    # --- Crop cycle ---
    if crop_insight:
        story.append(Paragraph("Cropping Pattern (NDVI)", ss["H2x"]))
        story.append(Paragraph(
            f"<b>{crop_insight['pattern']}</b> - "
            f"{crop_insight['cycles_per_year']} cycles/year, "
            f"mean cropland NDVI {crop_insight['mean_ndvi']}. "
            f"{crop_insight['detail']}", ss["Normal"]))
        if crop_insight.get("peak_months"):
            story.append(Paragraph(
                "Growth peaks: "
                + ", ".join(crop_insight["peak_months"]), ss["Normal"]))
        story.append(Spacer(1, 12))

    # --- Paddy ---
    if paddy:
        story.append(Paragraph("Paddy (Radar Detection)", ss["H2x"]))
        story.append(Paragraph(
            f"Detected <b>{paddy['paddy_ac']:,.0f} acres</b> of paddy - "
            f"{paddy['paddy_pct']}% of the buffer's cropland.",
            ss["Normal"]))
        story.append(Spacer(1, 12))

    # --- Rainfall ---
    if rain:
        story.append(Paragraph("Rainfall (10-year history)", ss["H2x"]))
        story.append(Paragraph(
            f"<b>{rain['verdict']}</b> - average "
            f"{rain['mean_annual_mm']:,} mm/year, variability "
            f"{rain['cv_pct']}%, monsoon share "
            f"{rain['monsoon_share_pct']}%. Wettest: "
            f"{rain['wettest_year']} ({rain['wettest_mm']:,} mm); "
            f"driest: {rain['driest_year']} ({rain['driest_mm']:,} mm). "
            f"{rain['detail']}", ss["Normal"]))

        annual = rain["annual"]
        fig, ax = plt.subplots(figsize=(7, 2.8))
        ax.bar(annual.index.astype(str), annual.values, color="#1565c0")
        ax.axhline(rain["mean_annual_mm"], ls="--", c="grey", lw=1)
        ax.set_ylabel("mm")
        story.append(Spacer(1, 6))
        story.append(_chart_image(fig, height=6 * cm))
        story.append(Spacer(1, 12))

    # --- Villages ---
    if villages_df is not None and not villages_df.empty:
        story.append(Paragraph("Villages in Buffer", ss["H2x"]))
        n_t = villages_df["Taluk"].nunique() if "Taluk" in villages_df else 0
        n_d = (villages_df["District"].nunique()
               if "District" in villages_df else 0)
        story.append(Paragraph(
            f"<b>{len(villages_df)}</b> villages across {n_t} taluks "
            f"and {n_d} districts.", ss["Normal"]))
        story.append(Spacer(1, 6))

    if insights_df is not None and not insights_df.empty:
        story.append(Paragraph(
            "Top Villages by Cropland", ss["H2x"]))
        top = insights_df.head(15)
        rows = [["Village", "Taluk", "Cropland (ac)",
                 "Pattern", "Cycles/Yr"]]
        for _, r in top.iterrows():
            rows.append([
                str(r["Village"])[:24],
                str(r["Taluk"])[:18],
                f"{r['Cropland (ac)']:,.0f}",
                r["Pattern"],
                r["Cycles/Year"],
            ])
        story.append(_table(
            rows, [4.5 * cm, 3.5 * cm, 2.6 * cm, 4 * cm, 1.8 * cm]))
        story.append(Spacer(1, 12))

    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "Sources: Sentinel-2, Sentinel-1 (ESA), Dynamic World (Google),"
        " WorldCover (ESA), CHIRPS (UCSB). Generated by "
        f"{APP_NAME} for {COMPANY}.",
        ParagraphStyle("foot", fontSize=7,
                       textColor=colors.grey)))

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=1.8 * cm, rightMargin=1.8 * cm,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        title="AgriRadius Pro - Area Report",
    )
    doc.build(story)

    return buf.getvalue()
