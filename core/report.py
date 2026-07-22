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
                      villages_df=None, insights_df=None,
                      stability=None, plantation=None, forecast=None,
                      soil_verdicts=None, scores_df=None,
                      mandi_df=None, soil_climate_df=None,
                      village_soil_df=None, allied=None,
                      mandi_hist=None, mandi_var=None):
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

    # --- Stability ---
    if stability:
        story.append(Paragraph("Cropland Stability (3 years)",
                               ss["H2x"]))
        by_year = ", ".join(
            f"{y}: {ac:,.0f} ac"
            for y, ac in sorted(stability["by_year"].items()))
        story.append(Paragraph(
            f"<b>{stability['verdict']}</b> "
            f"(year-to-year spread {stability['spread_pct']}%). "
            f"{by_year}. {stability['detail']}", ss["Normal"]))
        story.append(Spacer(1, 12))

    # --- Paddy ---
    if paddy:
        story.append(Paragraph("Paddy (Radar Detection)", ss["H2x"]))
        story.append(Paragraph(
            f"Detected <b>{paddy['paddy_ac']:,.0f} acres</b> of paddy - "
            f"{paddy['paddy_pct']}% of the buffer's cropland.",
            ss["Normal"]))
        story.append(Spacer(1, 12))

    # --- Plantation ---
    if plantation:
        story.append(Paragraph("Plantations (coconut/arecanut)",
                               ss["H2x"]))
        story.append(Paragraph(
            f"Likely plantation cover "
            f"<b>{plantation['plantation_ac']:,.0f} acres</b> - "
            f"{plantation['plantation_pct']}% of tree cover "
            f"({plantation['trees_ac']:,.0f} ac).", ss["Normal"]))
        story.append(Spacer(1, 12))

    # --- Soil ---
    if soil_verdicts:
        story.append(Paragraph("Soil Profile (0-30 cm)", ss["H2x"]))
        for label, verdict in soil_verdicts.items():
            story.append(Paragraph(
                f"<b>{label}:</b> {verdict}", ss["Normal"]))
        story.append(Spacer(1, 12))

    # --- Soil temperature & moisture ---
    if soil_climate_df is not None and not soil_climate_df.empty:
        story.append(Paragraph("Soil Temperature & Moisture",
                               ss["H2x"]))
        try:
            t = soil_climate_df["Soil Temp (°C)"].dropna()
            w = soil_climate_df["Soil Moisture (%)"].dropna()
            story.append(Paragraph(
                f"Mean soil temperature <b>{t.mean():.1f} °C</b> "
                f"(range {t.min():.1f}-{t.max():.1f} °C); mean soil "
                f"moisture <b>{w.mean():.1f}%</b>. (ERA5-Land, "
                f"area-level.)", ss["Normal"]))
        except Exception:
            pass
        story.append(Spacer(1, 12))

    # --- Per-village soil ---
    if village_soil_df is not None and not village_soil_df.empty:
        story.append(Paragraph("Per-Village Soil Profile", ss["H2x"]))
        cols = [c for c in ["Village", "Taluk", "pH", "OC (g/kg)",
                            "N (g/kg)", "CEC", "Texture"]
                if c in village_soil_df.columns]
        rows = [cols]
        for _, r in village_soil_df.head(40).iterrows():
            rows.append([str(r.get(c, "")) for c in cols])
        widths = [3.2, 2.8, 1.6, 2.0, 1.9, 1.5, 3.2][:len(cols)]
        story.append(_table(rows, [w * cm for w in widths]))
        if len(village_soil_df) > 40:
            story.append(Paragraph(
                f"...and {len(village_soil_df) - 40} more villages "
                "(full list in the Excel report).", ss["Normal"]))
        story.append(Spacer(1, 12))

    # --- Forecast ---
    if forecast:
        story.append(Paragraph("Weather Outlook (16 days)",
                               ss["H2x"]))
        dry = ""
        if forecast.get("dry_window_days"):
            dry = (f" Longest dry window: "
                   f"{forecast['dry_window_days']} days"
                   + (f" from {forecast['dry_window_start']}"
                      if forecast.get('dry_window_start') else "")
                   + ".")
        story.append(Paragraph(
            f"Rain next 7 days: <b>{forecast['rain_7d_mm']} mm</b> "
            f"over {forecast['rain_days_7d']} rainy days. "
            f"Temp range {forecast['tmin']}-{forecast['tmax']} C.{dry}",
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

        vcols = [c for c in ["Village", "Taluk", "District", "State"]
                 if c in villages_df.columns]
        vrows = [vcols]
        for _, r in villages_df.head(60).iterrows():
            vrows.append([str(r.get(c, "")) for c in vcols])
        vw = [4.2, 3.8, 4.0, 3.2][:len(vcols)]
        story.append(_table(vrows, [w * cm for w in vw]))
        if len(villages_df) > 60:
            story.append(Paragraph(
                f"...and {len(villages_df) - 60} more (full list in "
                "the Excel report).", ss["Normal"]))
        story.append(Spacer(1, 12))

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

    # --- Sourcing scores ---
    if scores_df is not None and not scores_df.empty:
        story.append(Paragraph(
            "Top Villages by Sourcing Score", ss["H2x"]))
        top = scores_df.head(15)
        rows = [["Rank", "Village", "Score", "Cropland (ac)",
                 "Pattern"]]
        for _, r in top.iterrows():
            rows.append([
                str(r.get("Rank", "")),
                str(r["Village"])[:22],
                str(r.get("Score", "")),
                f"{r.get('Cropland (ac)', 0):,.0f}",
                str(r.get("Pattern", ""))[:24],
            ])
        story.append(_table(
            rows, [1.4 * cm, 4 * cm, 1.8 * cm, 2.8 * cm, 5 * cm]))
        story.append(Spacer(1, 12))

    # --- Allied sectors & agri-economy ---
    if allied and allied.get("profile", {}).get("available"):
        p = allied["profile"]
        wr = p.get("within_radius", {})
        d = p.get("derived", {})
        story.append(Paragraph(
            "Allied Sectors & Agri-Economy", ss["H2x"]))
        story.append(Paragraph(
            "Livestock within radius (area-allocated from the 2019 "
            "Livestock Census):", ss["Normal"]))
        rows = [["Cattle", "Buffalo", "Goat", "Sheep", "Pig", "Poultry"],
                [f"{wr.get('cattle', 0):,}", f"{wr.get('buffalo', 0):,}",
                 f"{wr.get('goat', 0):,}", f"{wr.get('sheep', 0):,}",
                 f"{wr.get('pig', 0):,}", f"{wr.get('poultry', 0):,}"]]
        story.append(_table(rows, [2.5 * cm] * 6))
        story.append(Spacer(1, 4))
        story.append(Paragraph(
            f"Estimated dairy pool: <b>{d.get('milk_litres_per_day', 0):,}"
            f" L/day</b> ({d.get('milk_litres_per_year', 0):,} L/yr) from "
            f"~{d.get('milch_bovines', 0):,} in-milk bovines. Estimated "
            f"concentrate feed demand: <b>{d.get('total_feed_tpd', 0):,} "
            f"t/day</b> (bovine {d.get('bovine_feed_tpd', 0)} + poultry "
            f"{d.get('poultry_feed_tpd', 0)}).", ss["Normal"]))
        story.append(Spacer(1, 6))

        def _kv_line(dfr, label, cols):
            if dfr is None or dfr.empty:
                return
            parts = []
            for _, rr in dfr.iterrows():
                bits = [f"{rr.get(c)}" for c in cols if c in dfr.columns]
                parts.append(" ".join(str(b) for b in bits))
            story.append(Paragraph(
                f"<b>{label}:</b> " + " | ".join(parts), ss["Normal"]))

        _kv_line(allied.get("sericulture"), "Sericulture (state)",
                 ["state", "raw_silk_mt", "year"])
        _kv_line(allied.get("fisheries"), "Fisheries (state, inland MT)",
                 ["state", "inland_fish_mt", "year"])
        _kv_line(allied.get("fertilizer"), "Fertiliser (NPK kg/ha)",
                 ["state", "npk_kg_per_ha", "year"])
        _kv_line(allied.get("horticulture"),
                 "Horticulture (lakh ha / lakh t)",
                 ["state", "area_lakh_ha", "production_lakh_tonnes"])
        story.append(Spacer(1, 12))

    # --- Mandi prices ---
    if mandi_df is not None and not mandi_df.empty:
        story.append(Paragraph(
            "Mandi Prices (today, Rs/quintal)", ss["H2x"]))
        top = mandi_df.head(15)
        rows = [["Commodity", "Market", "District", "Modal"]]
        for _, r in top.iterrows():
            rows.append([
                str(r.get("Commodity", ""))[:16],
                str(r.get("Market", ""))[:22],
                str(r.get("District", ""))[:18],
                f"{r.get('Modal (Rs/qtl)', 0):,.0f}",
            ])
        story.append(_table(
            rows, [3.5 * cm, 4.5 * cm, 3.5 * cm, 2.5 * cm]))
        story.append(Spacer(1, 8))

        # Price trend (monthly modal) - compact recent table + summary
        if mandi_hist is not None and not mandi_hist.empty:
            h = mandi_hist.copy()
            first, last = h.iloc[0], h.iloc[-1]
            chg = last["Modal"] - first["Modal"]
            pct = 100 * chg / first["Modal"] if first["Modal"] else 0
            story.append(Paragraph(
                f"Price trend: latest <b>Rs{last['Modal']:,.0f}/qtl</b>, "
                f"period range Rs{h['Low'].min():,.0f}-"
                f"{h['High'].max():,.0f}, {pct:+.0f}% since "
                f"{first['Month'].strftime('%b %Y')}.", ss["Normal"]))
            recent = h.tail(12)
            rows = [["Month"] + [m.strftime("%b %y")
                                 for m in recent["Month"]]]
            rows.append(["Modal"] + [f"{v:,.0f}"
                                     for v in recent["Modal"]])
            story.append(_table(rows))
            story.append(Spacer(1, 6))

        # Variety / grade breakdown
        if mandi_var is not None and not mandi_var.empty:
            story.append(Paragraph(
                "Variety / grade breakdown (Rs/qtl):", ss["Normal"]))
            rows = [["Variety", "Latest", "Median", "Low", "High",
                     "Mkts"]]
            for _, r in mandi_var.head(8).iterrows():
                rows.append([
                    str(r.get("Variety", ""))[:18],
                    f"{r.get('Latest', 0):,}",
                    f"{r.get('Median', 0):,}",
                    f"{r.get('Low', 0):,}",
                    f"{r.get('High', 0):,}",
                    str(r.get("Markets", "")),
                ])
            story.append(_table(
                rows, [4 * cm, 2.4 * cm, 2.4 * cm, 2.2 * cm, 2.2 * cm,
                       1.6 * cm]))
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
