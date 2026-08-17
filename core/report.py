"""Area Report - one PDF assembling EVERY analysis for the buffer.

The rule here is simple: whatever the app shows on screen goes into
this PDF. Sections appear only if their analysis produced data, tables
are printed in full (long ones are chunked across pages rather than
truncated), and every chart the tabs draw is redrawn here.

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
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

GREEN = colors.HexColor("#2e7d32")
LIGHT = colors.HexColor("#f1f8e9")

# Wide tables are printed in full; this is only how many rows go into
# one Table object before it is split, which keeps memory sane.
CHUNK = 45


def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle(
        "H1x", parent=ss["Heading1"], textColor=GREEN))
    ss.add(ParagraphStyle(
        "H2x", parent=ss["Heading2"], textColor=GREEN))
    ss.add(ParagraphStyle(
        "Small", parent=ss["Normal"], fontSize=8,
        textColor=colors.HexColor("#555555")))
    return ss


def _table(data, col_widths=None, font_size=9):
    t = Table(data, colWidths=col_widths, hAlign="LEFT",
              repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), GREEN),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def _df_table(story, df, columns=None, widths=None, font_size=8,
              max_chars=28):
    """Print a whole DataFrame as one or more tables - no truncation."""
    if df is None or len(df) == 0:
        return
    cols = [c for c in (columns or list(df.columns))
            if c in df.columns]
    if not cols:
        return

    def cell(v):
        s = "" if v is None else str(v)
        if s in ("nan", "None", "NaT"):
            return ""
        return s[:max_chars]

    rows = df[cols].values.tolist()
    for i in range(0, len(rows), CHUNK):
        data = [cols] + [[cell(v) for v in r]
                         for r in rows[i:i + CHUNK]]
        story.append(_table(data, widths, font_size=font_size))
        story.append(Spacer(1, 4))


def _legend_table(legend, per_row=3):
    """A small colour-swatch legend: [(hex_or_'_base', label), ...]."""
    if not legend:
        return None
    items = [("#888888" if h == "_base" else "#" + str(h).lstrip("#"),
              lbl) for h, lbl in legend]
    data, styles = [], []
    for i in range(0, len(items), per_row):
        chunk = items[i:i + per_row]
        row, r = [], len(data)
        for c, (color, lbl) in enumerate(chunk):
            row += [" ", lbl]
            try:
                swatch = colors.HexColor(color)
            except Exception:
                swatch = colors.grey
            styles.append(("BACKGROUND", (c * 2, r), (c * 2, r),
                           swatch))
            styles.append(("BOX", (c * 2, r), (c * 2, r), 0.4,
                           colors.grey))
        while len(row) < per_row * 2:
            row += ["", ""]
        data.append(row)
    widths = []
    for _ in range(per_row):
        widths += [0.55 * cm, 4.3 * cm]
    t = Table(data, colWidths=widths, hAlign="CENTER")
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
    ] + styles))
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
                      mandi_hist=None, mandi_var=None,
                      map_images=None,
                      ndvi_df=None, rain_df=None, forecast_days=None,
                      soil_profile=None, maize=None, aquaculture=None,
                      shc_summary=None, fertilizer=None,
                      fertilizer_crop=None, capability=None,
                      coconut_survey=None, coconut_villages=None,
                      coconut_validation=None,
                      gt_df=None, cards_df=None, notes=None,
                      irrigation=None, irrigation_note=None,
                      irrigation_rank=None, irrigation_sat=None,
                      irrigation_verdict=None,
                      irrigation_villages=None,
                      irrigation_villages_summary=None):
    """Assemble the full PDF. Returns bytes."""

    ss = _styles()
    story = []

    from config import APP_NAME, COMPANY, LOGO_PATH

    # ---------------- Cover ----------------
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
    story.append(Spacer(1, 10))

    # ---------------- At a glance ----------------
    kv = []
    if crosscheck:
        kv.append(["Confirmed cropland",
                   f"{crosscheck['confirmed_ac']:,.0f} ac "
                   f"({crosscheck['agreement_pct']}% agreement)"])
    if stability:
        kv.append(["Cropland stability", stability["verdict"]])
    if crop_insight:
        kv.append(["Cropping pattern",
                   f"{crop_insight['pattern']} - "
                   f"{crop_insight['cycles_per_year']} cycles/yr"])
    if paddy:
        kv.append(["Paddy", f"{paddy['paddy_ac']:,.0f} ac"])
    if plantation:
        kv.append(["Plantation",
                   f"{plantation['plantation_ac']:,.0f} ac"])
    if maize:
        kv.append(["Maize / kharif crop",
                   f"{maize.get('maize_ac', 0):,.0f} ac"])
    if aquaculture:
        kv.append(["Aquaculture ponds",
                   f"{aquaculture.get('pond_ac', 0):,.0f} ac"])
    if coconut_survey:
        kv.append(["Coconut (govt survey)",
                   f"{coconut_survey['extent_ac']:,} ac recorded"])
    if rain:
        kv.append(["Rainfall",
                   f"{rain['verdict']} - "
                   f"{rain['mean_annual_mm']:,} mm/yr"])
    if forecast:
        kv.append(["Rain next 7 days",
                   f"{forecast['rain_7d_mm']} mm"])
    if shc_summary:
        kv.append(["Measured soil samples",
                   f"{shc_summary['samples']:,} "
                   f"(cycle {shc_summary['cycle']})"])
    if villages_df is not None and len(villages_df):
        kv.append(["Villages in area", f"{len(villages_df):,}"])
    if kv:
        story.append(Paragraph("At a Glance", ss["H2x"]))
        story.append(_table([["Measure", "Value"]] + kv,
                            [6 * cm, 9 * cm]))
        story.append(Spacer(1, 12))

    # ---------------- Land cover ----------------
    if landcover_df is not None and not landcover_df.empty:
        story.append(Paragraph("Land Cover", ss["H2x"]))
        total = landcover_df["Area (acres)"].sum()
        rows = [["Land Cover", "Area (acres)", "Share"]]
        for _, r in landcover_df.iterrows():
            share = (r["Area (acres)"] / total * 100) if total else 0
            rows.append([r["Land Cover"],
                         f"{r['Area (acres)']:,.0f}",
                         f"{share:.1f}%"])
        rows.append(["Total", f"{total:,.0f}", "100%"])
        story.append(_table(rows, [6 * cm, 4.5 * cm, 3 * cm]))

        top = landcover_df.nlargest(8, "Area (acres)")
        fig, ax = plt.subplots(figsize=(7, 3))
        ax.bar(top["Land Cover"], top["Area (acres)"], color="#2e7d32")
        ax.set_ylabel("Acres")
        ax.tick_params(axis="x", rotation=20)
        story.append(Spacer(1, 6))
        story.append(_chart_image(fig))
        story.append(Spacer(1, 12))

    # ---------------- Confidence ----------------
    if crosscheck:
        story.append(Paragraph("Cropland Confidence", ss["H2x"]))
        story.append(Paragraph(
            f"Two independent datasets agree on "
            f"<b>{crosscheck['confirmed_ac']:,.0f} acres</b> of cropland "
            f"({crosscheck['agreement_pct']}% agreement).", ss["Normal"]))
        story.append(Spacer(1, 12))

    # ---------------- Crop cycle + NDVI chart ----------------
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
        story.append(Spacer(1, 6))

    if ndvi_df is not None and len(ndvi_df) and "NDVI" in ndvi_df:
        try:
            d = ndvi_df.dropna(subset=["NDVI"])
            if len(d):
                fig, ax = plt.subplots(figsize=(7, 2.8))
                ax.plot(range(len(d)), d["NDVI"], marker="o",
                        color="#2e7d32", lw=1.5, ms=3)
                labs = [str(x) for x in d.get("Month", d.index)]
                ax.set_xticks(range(len(d)))
                ax.set_xticklabels(labs, rotation=60, fontsize=6)
                ax.set_ylabel("NDVI")
                ax.grid(alpha=.3)
                story.append(_chart_image(fig, height=6 * cm))
                story.append(Paragraph(
                    "Monthly cropland NDVI - each hump is one crop "
                    "cycle.", ss["Small"]))
                story.append(Spacer(1, 6))
        except Exception:
            pass
        _df_table(story, ndvi_df, widths=[5 * cm, 4 * cm],
                  font_size=8)
        story.append(Spacer(1, 12))

    # ---------------- Stability ----------------
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
        try:
            ys = sorted(stability["by_year"].items())
            fig, ax = plt.subplots(figsize=(7, 2.4))
            ax.bar([str(y) for y, _ in ys], [a for _, a in ys],
                   color="#558b2f")
            ax.set_ylabel("Cropland (ac)")
            story.append(Spacer(1, 6))
            story.append(_chart_image(fig, height=5 * cm))
        except Exception:
            pass
        story.append(Spacer(1, 12))

    # ---------------- Detections ----------------
    det_rows = []
    if paddy:
        det_rows.append(["Paddy (radar)",
                         f"{paddy['paddy_ac']:,.0f} ac",
                         f"{paddy['paddy_pct']}% of cropland"])
    if plantation:
        det_rows.append(["Plantation (coconut/arecanut)",
                         f"{plantation['plantation_ac']:,.0f} ac",
                         f"{plantation['plantation_pct']}% of tree "
                         f"cover ({plantation['trees_ac']:,.0f} ac)"])
    if maize:
        det_rows.append(["Maize / kharif crop",
                         f"{maize.get('maize_ac', 0):,.0f} ac", "-"])
    if aquaculture:
        det_rows.append(["Aquaculture ponds",
                         f"{aquaculture.get('pond_ac', 0):,.0f} ac",
                         "-"])
    if det_rows:
        story.append(Paragraph("Crop & Land-Use Detections", ss["H2x"]))
        story.append(_table(
            [["Layer", "Area", "Context"]] + det_rows,
            [6 * cm, 3.5 * cm, 6 * cm]))
        story.append(Spacer(1, 12))

    # ---------------- Coconut crop survey (measured) ----------------
    if coconut_survey:
        story.append(Paragraph(
            "Coconut - Government Crop Survey (measured)", ss["H2x"]))
        s = coconut_survey
        story.append(_table([
            ["Coconut land recorded", "Plots", "Growers", "Villages",
             "Irrigated"],
            [f"{s['extent_ac']:,} ac", f"{s['parcels']:,}",
             f"{s['farmers']:,}", f"{s['villages']:,}",
             f"{s.get('irrigated_pct', 0)}%"],
        ], [4 * cm, 2.6 * cm, 2.6 * cm, 2.4 * cm, 2.4 * cm]))
        story.append(Paragraph(
            "Every coconut plot logged against its survey number in "
            "the Karnataka crop survey (2023-24 Kharif), matched to "
            "its village polygon. Ground records, not satellite.",
            ss["Small"]))
        story.append(Spacer(1, 6))

        if coconut_validation:
            v = coconut_validation
            story.append(_table([
                ["Survey coconut land", "Satellite detected",
                 "Detection vs survey"],
                [f"{v['survey_ac']:,} ac", f"{v['detected_ac']:,} ac",
                 f"{v['ratio_pct']}%"],
            ], [5 * cm, 5 * cm, 5 * cm]))
            story.append(Paragraph(v["verdict"], ss["Small"]))
            story.append(Spacer(1, 6))

        if coconut_villages:
            import pandas as pd
            cv = pd.DataFrame(coconut_villages)
            story.append(Paragraph(
                f"All {len(cv):,} villages with recorded coconut, "
                "ranked by area:", ss["Normal"]))
            _df_table(story, cv,
                      columns=["village", "taluk", "district",
                               "coconut_ac", "parcels", "farmers",
                               "irrigated_pct", "intensity_pct"],
                      widths=[3.4 * cm, 2.8 * cm, 2.6 * cm, 2 * cm,
                              1.6 * cm, 1.6 * cm, 1.6 * cm, 1.8 * cm])
        story.append(Spacer(1, 12))

    # ---------------- Irrigation ----------------
    if irrigation or irrigation_sat:
        story.append(Paragraph(
            "Irrigation - How This Land Is Watered", ss["H2x"]))

    if irrigation:
        story.append(Paragraph(
            "District irrigation by SOURCE (Land Use Statistics, "
            "DES-Agri 2022-23). Karnataka's net irrigated area is "
            "5.04 million ha and 56.6% of it is borewell/tubewell - "
            "so the source split, not the total, decides how "
            "irrigated farms can be found.", ss["Normal"]))
        story.append(_table([
            ["Net irrigated", "Borewell share", "Canal share",
             "Gross : net"],
            [f"{irrigation['net_ac']:,} ac",
             (f"{irrigation['borewell_pct']:.0f}%"
              if irrigation.get("borewell_pct") is not None else "-"),
             (f"{irrigation['canal_pct']:.0f}%"
              if irrigation.get("canal_pct") is not None else "-"),
             (f"{irrigation['intensity']}x"
              if irrigation.get("intensity") else "-")],
        ], [4 * cm, 3.5 * cm, 3.5 * cm, 3.5 * cm]))
        story.append(Spacer(1, 4))

        rows = [["Irrigation source", "Area (ha)", "Share"]]
        for col, label in [("Borewell/Tubewell", "Borewell / tubewell"),
                           ("Canal (Government)", "Canal (government)"),
                           ("Canal (Private)", "Canal (private)"),
                           ("Open/Dug Well", "Open / dug well"),
                           ("Tank", "Tank"),
                           ("Other Source", "Other (mostly lift)")]:
            area = (irrigation.get("sources") or {}).get(col) or 0
            share = (irrigation.get("shares") or {}).get(col)
            if area:
                rows.append([label, f"{area:,.0f}",
                             f"{share}%" if share is not None else "-"])
        if len(rows) > 1:
            story.append(_table(rows, [6 * cm, 4 * cm, 3 * cm]))
            try:
                labs = [r[0] for r in rows[1:]]
                vals = [float(str(r[2]).rstrip("%") or 0)
                        for r in rows[1:]]
                fig, ax = plt.subplots(figsize=(7, 2.6))
                ax.barh(labs[::-1], vals[::-1], color="#0277bd")
                ax.set_xlabel("% of net irrigated area")
                story.append(Spacer(1, 6))
                story.append(_chart_image(fig, height=5.5 * cm))
            except Exception:
                pass

        if irrigation_note:
            story.append(Spacer(1, 4))
            story.append(Paragraph(
                f"<b>How to target field staff here:</b> "
                f"{irrigation_note}", ss["Normal"]))
        story.append(Paragraph(
            f"Districts: {', '.join(irrigation.get('districts', []))} "
            f"· {irrigation.get('vintage', '')}", ss["Small"]))
        story.append(Spacer(1, 8))

        if irrigation_rank:
            try:
                import pandas as pd
                story.append(Paragraph(
                    "District detail", ss["Normal"]))
                _df_table(story, pd.DataFrame(irrigation_rank),
                          font_size=8)
            except Exception:
                pass

    if irrigation_sat:
        story.append(Paragraph(
            "Satellite measurement of irrigated cropland",
            ss["Normal"]))
        if irrigation_verdict:
            story.append(Paragraph(f"<b>{irrigation_verdict}</b>",
                                   ss["Normal"]))
        s = irrigation_sat
        rows = [["Method", "Irrigated area", "Reliability"]]
        for key, label, note in [
                ("evidence_2plus_ac", "TWO OR MORE methods agree",
                 "The defensible headline - independent methods "
                 "concurring, not one product trusted alone"),
                ("evidence_3plus_ac", "THREE OR MORE methods agree",
                 "Send field staff here first"),
                ("s1_event_ac", "Radar irrigation events (S1)",
                 "Works under cloud - carries coastal Karnataka and "
                 "Malnad; ~86% discrimination published"),
                ("groundwater_fed_ac", "Borewell-fed (inferred)",
                 "Irrigated land far from permanent surface water - "
                 "will never appear on a canal command-area map"),
                ("surface_fed_ac", "Canal/tank-fed (inferred)",
                 "Irrigated land within 1.5 km of permanent water"),
                ("summer_green_ac", "Summer green (Feb-May, ours)",
                 "Primary signal - nothing stays green through a "
                 "Karnataka summer without applied water"),
                ("multicrop_ac", "Multi-crop (2+ crops/yr)",
                 "Near-conclusive in the semi-arid interior"),
                ("lgrip_irrigated_ac", "LGRIP30 irrigated",
                 "91% accuracy is US-only; India version V001, no "
                 "published Indian accuracy"),
                ("lgrip_rainfed_ac", "LGRIP30 rain-fed",
                 "Rain-fed user's accuracy only 63% in South Asia"),
                ("worldcereal_irrigated_ac", "WorldCereal irrigation",
                 "LOWER BOUND - no published accuracy, under-maps "
                 "Asia"),
                ("confirmed_ac", "Both methods agree",
                 "Summer green AND LGRIP30 - the number to quote")]:
            v = s.get(key)
            rows.append([label,
                         f"{v:,.0f} ac" if v is not None else "n/a",
                         note])
        story.append(_table(rows, [4.6 * cm, 2.8 * cm, 7.6 * cm],
                            font_size=7))
        zone = (irrigation_sat.get("zone") or {})
        if zone.get("label"):
            story.append(Paragraph(
                f"<b>Zone:</b> {zone['label']} - expect "
                f"{zone.get('accuracy', 'variable accuracy')}. "
                f"{zone.get('note', '')}", ss["Small"]))
        story.append(Paragraph(
            "Rabi greenness is deliberately NOT used: rabi jowar, "
            "chickpea and safflower on black cotton soil in "
            "Vijayapura, Bagalkote, Kalaburagi, Bidar and "
            "Vijayanagara are rain-fed on stored vertisol moisture, "
            "and a 'green in rabi = irrigated' rule mislabels much of "
            "north Karnataka. Expect 80-90% parcel accuracy in the "
            "dry interior, 60-75% on the coast and in Malnad.",
            ss["Small"]))
        story.append(Spacer(1, 12))

    if irrigation_villages is not None and len(irrigation_villages):
        story.append(Paragraph(
            "Irrigation village by village (measured per polygon)",
            ss["Normal"]))
        vs = irrigation_villages_summary or {}
        if vs:
            story.append(_table([
                ["Villages", "Irrigated", "Likely borewell-fed",
                 "2+ methods agree"],
                [f"{vs.get('villages', 0):,}",
                 f"{vs.get('irrigated_ac', 0):,} ac"
                 + (f" ({vs['irrigated_pct']}%)"
                    if vs.get("irrigated_pct") is not None else ""),
                 f"{vs.get('borewell_fed_ac', 0):,} ac",
                 f"{vs.get('agree_2plus_ac', 0):,} ac"],
            ], [3 * cm, 4.5 * cm, 4 * cm, 4 * cm]))
            story.append(Paragraph(
                f"{vs.get('heavily_irrigated_villages', 0)} villages "
                f"are 40%+ irrigated; "
                f"{vs.get('rainfed_villages', 0)} are effectively "
                f"rain-fed. The government source split is published "
                f"per district only, so these village figures are "
                f"measured from each village's own polygon.",
                ss["Small"]))
            story.append(Spacer(1, 4))
        _df_table(
            story, irrigation_villages,
            columns=["village", "taluk", "district", "cropland_ac",
                     "irrigated_ac", "irrigated_pct",
                     "radar_event_ac", "borewell_fed_ac",
                     "agree_2plus_ac", "district_borewell_pct",
                     "district_canal_pct"],
            widths=[2.9 * cm, 2.3 * cm, 2.2 * cm, 1.7 * cm, 1.7 * cm,
                    1.5 * cm, 1.7 * cm, 1.8 * cm, 1.8 * cm, 1.6 * cm,
                    1.5 * cm],
            font_size=6)
        story.append(Spacer(1, 12))

    # ---------------- Modelled soil ----------------
    if soil_verdicts:
        story.append(Paragraph("Soil Profile (0-30 cm, modelled)",
                               ss["H2x"]))
        for label, verdict in soil_verdicts.items():
            story.append(Paragraph(
                f"<b>{label}:</b> {verdict}", ss["Normal"]))
        if soil_profile:
            rows = [["Property", "Value"]]
            for k, v in soil_profile.items():
                if v is not None:
                    rows.append([str(k), str(v)])
            if len(rows) > 1:
                story.append(Spacer(1, 4))
                story.append(_table(rows, [6 * cm, 4 * cm]))
        story.append(Paragraph(
            "SoilGrids (ISRIC) modelled estimates at 250 m. Phosphorus "
            "and potassium cannot be sensed from space - see the "
            "measured Soil Health Card section below.", ss["Small"]))
        story.append(Spacer(1, 12))

    # ---------------- Measured soil test (SHC) ----------------
    if shc_summary:
        story.append(Paragraph(
            "Measured Soil Test - Soil Health Cards", ss["H2x"]))
        story.append(Paragraph(
            f"{shc_summary['samples']:,} lab-tested farmer samples, "
            f"cycle {shc_summary['cycle']}. Districts: "
            f"{', '.join(shc_summary.get('districts', []))}.",
            ss["Normal"]))
        rows = [["Nutrient", "% Low", "% Medium", "% High",
                 "Dominant"]]
        for _, m in (shc_summary.get("macros") or {}).items():
            rows.append([m["label"], f"{m['low']}%", f"{m['med']}%",
                         f"{m['high']}%", m["dominant"]])
        story.append(Spacer(1, 4))
        story.append(_table(rows, [5 * cm, 2.4 * cm, 2.6 * cm,
                                   2.4 * cm, 2.6 * cm]))

        ph = shc_summary.get("ph") or {}
        story.append(Spacer(1, 4))
        story.append(Paragraph(
            f"Soil reaction: {ph.get('acid', 0)}% acidic, "
            f"{ph.get('neut', 0)}% neutral, {ph.get('alk', 0)}% "
            f"alkaline (dominant: <b>{ph.get('dominant', '-')}</b>). "
            f"Salinity: {shc_summary.get('ec_saline', 0)}% of samples "
            f"saline.", ss["Normal"]))

        micros = shc_summary.get("micros") or {}
        if micros:
            rows = [["Micronutrient", "% samples deficient", "Advice"]]
            for _, m in micros.items():
                rows.append([m["label"], f"{m['deficient_pct']}%",
                             m.get("advice", "")[:60]])
            story.append(Spacer(1, 6))
            story.append(_table(rows, [3.4 * cm, 3.2 * cm, 8.4 * cm],
                                font_size=8))
        story.append(Spacer(1, 12))

    # ---------------- Fertiliser guidance ----------------
    if fertilizer:
        story.append(Paragraph(
            f"Fertiliser Guidance - {fertilizer_crop or 'selected crop'}",
            ss["H2x"]))
        rows = [["Nutrient", "Soil class", "Recommended dose",
                 "Adjustment", "Apply"]]
        for r in fertilizer.get("rows", []):
            rows.append([r["nutrient"], r["soil_class"],
                         f"{r['rdf']} {fertilizer.get('unit', '')}",
                         f"x{r['factor']}",
                         f"{r['adjusted']} {fertilizer.get('unit', '')}"])
        story.append(_table(rows, [2.6 * cm, 2.6 * cm, 3.6 * cm,
                                   2.4 * cm, 3.4 * cm]))
        for n in fertilizer.get("notes", []):
            story.append(Paragraph(f"- {n}", ss["Normal"]))
        story.append(Paragraph(
            "Soil-test-adjusted doses, area-level. Always prefer the "
            "farmer's own Soil Health Card and local KVK advice.",
            ss["Small"]))
        story.append(Spacer(1, 12))

    # ---------------- Land capability (SLUSI) ----------------
    if capability is not None and len(capability):
        story.append(Paragraph("Land Capability (SLUSI)", ss["H2x"]))
        try:
            import pandas as pd
            cap = (capability if isinstance(capability, pd.DataFrame)
                   else pd.DataFrame(capability))
            _df_table(story, cap, font_size=8)
        except Exception:
            pass
        story.append(Spacer(1, 12))

    # ---------------- Soil temperature & moisture ----------------
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
            fig, ax = plt.subplots(figsize=(7, 2.6))
            ax.plot(range(len(soil_climate_df)),
                    soil_climate_df["Soil Temp (°C)"],
                    color="#e65100", label="Soil temp (°C)")
            ax2 = ax.twinx()
            ax2.plot(range(len(soil_climate_df)),
                     soil_climate_df["Soil Moisture (%)"],
                     color="#1565c0", label="Soil moisture (%)")
            ax.set_ylabel("°C", color="#e65100")
            ax2.set_ylabel("%", color="#1565c0")
            ax.grid(alpha=.3)
            story.append(Spacer(1, 6))
            story.append(_chart_image(fig, height=5.5 * cm))
        except Exception:
            pass
        _df_table(story, soil_climate_df, font_size=8)
        story.append(Spacer(1, 12))

    # ---------------- Per-village soil (FULL) ----------------
    if village_soil_df is not None and not village_soil_df.empty:
        story.append(Paragraph("Per-Village Soil Profile", ss["H2x"]))
        story.append(Paragraph(
            f"All {len(village_soil_df):,} villages.", ss["Normal"]))
        cols = [c for c in ["Village", "Taluk", "pH", "OC (g/kg)",
                            "N (g/kg)", "CEC", "Texture"]
                if c in village_soil_df.columns]
        widths = [3.2, 2.8, 1.6, 2.0, 1.9, 1.5, 3.2][:len(cols)]
        _df_table(story, village_soil_df, columns=cols,
                  widths=[w * cm for w in widths])
        story.append(Spacer(1, 12))

    # ---------------- Forecast ----------------
    if forecast:
        story.append(Paragraph("Weather Outlook (16 days)", ss["H2x"]))
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
        story.append(Spacer(1, 6))

    if forecast_days is not None and len(forecast_days):
        try:
            fd = forecast_days
            rain_col = next((c for c in fd.columns
                             if "rain" in str(c).lower()
                             or "precip" in str(c).lower()), None)
            if rain_col:
                fig, ax = plt.subplots(figsize=(7, 2.4))
                ax.bar(range(len(fd)), fd[rain_col], color="#0288d1")
                ax.set_ylabel("mm")
                ax.set_xlabel("day ahead")
                story.append(_chart_image(fig, height=5 * cm))
                story.append(Spacer(1, 4))
        except Exception:
            pass
        _df_table(story, forecast_days, font_size=7)
        story.append(Spacer(1, 12))

    # ---------------- Rainfall ----------------
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
        story.append(Spacer(1, 6))

    if rain_df is not None and len(rain_df):
        try:
            col = next((c for c in rain_df.columns
                        if "rain" in str(c).lower()
                        or "mm" in str(c).lower()), None)
            if col:
                fig, ax = plt.subplots(figsize=(7, 2.4))
                ax.plot(range(len(rain_df)), rain_df[col],
                        color="#0d47a1", lw=1)
                ax.set_ylabel("mm / month")
                ax.grid(alpha=.3)
                story.append(_chart_image(fig, height=5 * cm))
                story.append(Paragraph(
                    "Monthly rainfall across the full history.",
                    ss["Small"]))
                story.append(Spacer(1, 4))
        except Exception:
            pass
        _df_table(story, rain_df, font_size=7)
        story.append(Spacer(1, 12))

    # ---------------- Villages (FULL) ----------------
    if villages_df is not None and not villages_df.empty:
        story.append(Paragraph("Villages in Buffer", ss["H2x"]))
        n_t = villages_df["Taluk"].nunique() if "Taluk" in villages_df else 0
        n_d = (villages_df["District"].nunique()
               if "District" in villages_df else 0)
        story.append(Paragraph(
            f"<b>{len(villages_df)}</b> villages across {n_t} taluks "
            f"and {n_d} districts - complete list:", ss["Normal"]))
        story.append(Spacer(1, 6))
        vcols = [c for c in ["Village", "Taluk", "District", "State"]
                 if c in villages_df.columns]
        vw = [4.2, 3.8, 4.0, 3.2][:len(vcols)]
        _df_table(story, villages_df, columns=vcols,
                  widths=[w * cm for w in vw])
        story.append(Spacer(1, 12))

    # ---------------- Village insights (FULL) ----------------
    if insights_df is not None and not insights_df.empty:
        story.append(Paragraph(
            "Village Cropland & Cropping Pattern", ss["H2x"]))
        story.append(Paragraph(
            f"All {len(insights_df):,} analysed villages.",
            ss["Normal"]))
        cols = [c for c in ["Village", "Taluk", "Cropland (ac)",
                            "Pattern", "Cycles/Year"]
                if c in insights_df.columns]
        _df_table(story, insights_df, columns=cols,
                  widths=[4.5 * cm, 3.5 * cm, 2.6 * cm, 4 * cm,
                          1.8 * cm])
        story.append(Spacer(1, 12))

    # ---------------- Sourcing scores (FULL) ----------------
    if scores_df is not None and not scores_df.empty:
        story.append(Paragraph("Village Sourcing Scores", ss["H2x"]))
        story.append(Paragraph(
            f"All {len(scores_df):,} scored villages, best first.",
            ss["Normal"]))
        cols = [c for c in ["Rank", "Village", "Score",
                            "Cropland (ac)", "Pattern"]
                if c in scores_df.columns]
        _df_table(story, scores_df, columns=cols,
                  widths=[1.4 * cm, 4 * cm, 1.8 * cm, 2.8 * cm,
                          5 * cm])
        story.append(Spacer(1, 12))

    # ---------------- Allied sectors ----------------
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
        story.append(Spacer(1, 8))

        for key, label in (("sericulture", "Sericulture (state)"),
                           ("fisheries", "Fisheries (state)"),
                           ("fertilizer", "Fertiliser use (state)"),
                           ("horticulture", "Horticulture (state)")):
            dfr = allied.get(key)
            if dfr is not None and len(dfr):
                story.append(Paragraph(label, ss["Normal"]))
                _df_table(story, dfr, font_size=8)
        story.append(Spacer(1, 12))

    # ---------------- Mandi prices ----------------
    if mandi_df is not None and not mandi_df.empty:
        story.append(Paragraph(
            "Mandi Prices (today, Rs/quintal)", ss["H2x"]))
        _df_table(story, mandi_df, font_size=8)
        story.append(Spacer(1, 6))

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
            try:
                fig, ax = plt.subplots(figsize=(7, 2.6))
                ax.plot(range(len(h)), h["Modal"], color="#6a1b9a",
                        marker="o", ms=3)
                ax.fill_between(range(len(h)), h["Low"], h["High"],
                                color="#ce93d8", alpha=.35)
                ax.set_xticks(range(len(h)))
                ax.set_xticklabels([m.strftime("%b %y")
                                    for m in h["Month"]],
                                   rotation=60, fontsize=6)
                ax.set_ylabel("Rs/qtl")
                ax.grid(alpha=.3)
                story.append(Spacer(1, 4))
                story.append(_chart_image(fig, height=5.5 * cm))
            except Exception:
                pass
            story.append(Spacer(1, 4))
            _df_table(story, h, font_size=7)
            story.append(Spacer(1, 6))

        if mandi_var is not None and not mandi_var.empty:
            story.append(Paragraph(
                "Variety / grade breakdown (Rs/qtl):", ss["Normal"]))
            _df_table(story, mandi_var, font_size=8)
        story.append(Spacer(1, 12))

    # ---------------- Field data (ground truth) ----------------
    if gt_df is not None and len(gt_df):
        story.append(Paragraph(
            "Field Observations (your team's ground truth)", ss["H2x"]))
        _df_table(story, gt_df, font_size=7)
        story.append(Spacer(1, 10))

    if cards_df is not None and len(cards_df):
        story.append(Paragraph(
            "Soil Health Cards collected in the field", ss["H2x"]))
        _df_table(story, cards_df, font_size=7)
        story.append(Spacer(1, 12))

    # ---------------- Detection evidence: every map ----------------
    if map_images:
        cap = ss["Small"]

        story.append(PageBreak())
        story.append(Paragraph(
            "Map Layers - Visual Evidence", ss["H1x"]))
        story.append(Paragraph(
            "Every map layer the app can display, rendered from the "
            "same imagery and datasets that produced the numbers "
            "above. Each is clipped to your "
            f"{meta['radius']} km analysis area around "
            f"{meta['lat']:.4f}, {meta['lon']:.4f} for year "
            f"{meta['year']}.", ss["Normal"]))
        story.append(Spacer(1, 10))

        stat_style = ParagraphStyle(
            "stat", parent=ss["Normal"], fontSize=9, textColor=GREEN)

        def _stat_for(mi):
            k = mi.get("kind")
            try:
                if k == "plantation" and plantation:
                    return (f"Measured here: "
                            f"{plantation['plantation_ac']:,.0f} acres of "
                            f"plantation ({plantation['plantation_pct']}% "
                            f"of the area).")
                if k == "paddy" and paddy:
                    return (f"Measured here: {paddy['paddy_ac']:,.0f} "
                            f"acres of paddy ({paddy['paddy_pct']}% of "
                            f"cropland).")
                if k == "maize" and maize:
                    return (f"Measured here: "
                            f"{maize.get('maize_ac', 0):,.0f} acres of "
                            f"maize / kharif crop.")
                if k == "aquaculture" and aquaculture:
                    return (f"Measured here: "
                            f"{aquaculture.get('pond_ac', 0):,.0f} acres "
                            f"of ponds.")
                if k == "landcover" and landcover_df is not None \
                        and not landcover_df.empty:
                    tot = landcover_df["Area (acres)"].sum()
                    top = landcover_df.nlargest(3, "Area (acres)")
                    parts = [f"{r['Land Cover']} "
                             f"{100*r['Area (acres)']/tot:.0f}%"
                             for _, r in top.iterrows()] if tot else []
                    return "Dominant cover: " + ", ".join(parts) + "."
                if k == "ndvi" and crop_insight:
                    return (f"Mean cropland NDVI "
                            f"{crop_insight.get('mean_ndvi')}; pattern: "
                            f"{crop_insight.get('pattern')}.")
                if k in ("satellite", "confidence") and crosscheck:
                    return (f"Confirmed cropland: "
                            f"{crosscheck['confirmed_ac']:,.0f} ac "
                            f"({crosscheck['agreement_pct']}% agreement "
                            f"between two datasets).")
                if k == "shc" and shc_summary:
                    return (f"{shc_summary['samples']:,} lab samples, "
                            f"cycle {shc_summary['cycle']}.")
                if k == "coconut_survey" and coconut_survey:
                    return (f"{coconut_survey['extent_ac']:,} ac of "
                            f"coconut recorded across "
                            f"{coconut_survey['villages']} villages.")
            except Exception:
                return None
            return None

        for mi in map_images:
            try:
                png = mi.get("png")
                if not png:
                    continue
                block = [Paragraph(mi.get("title", "Map"), ss["H2x"]),
                         Image(BytesIO(png), width=9.6 * cm,
                               height=9.6 * cm, kind="proportional",
                               hAlign="CENTER")]
                stat = _stat_for(mi)
                if stat:
                    block.append(Paragraph(stat, stat_style))
                lt = _legend_table(mi.get("legend"))
                if lt is not None:
                    block.append(Spacer(1, 2))
                    block.append(lt)
                if mi.get("caption"):
                    block.append(Paragraph(mi["caption"], cap))
                block.append(Spacer(1, 14))
                story.append(KeepTogether(block))
            except Exception:
                continue

        story.append(Spacer(1, 6))
        story.append(Paragraph(
            "How to read these: coloured detection overlays sit on top "
            "of the true-colour satellite image, so you can judge the "
            "fit against real fields. Land cover, NDVI and the soil "
            "layers are standalone renders. The soil-test and coconut "
            "survey maps are MEASURED ground records, not model "
            "output. Satellite layers are model outputs at 10 m - "
            "trust the pattern and verify edges on the ground.", cap))

    # ---------------- Notes / methodology ----------------
    if notes:
        story.append(PageBreak())
        story.append(Paragraph("Notes & Coverage", ss["H2x"]))
        for n in notes:
            story.append(Paragraph(f"- {n}", ss["Normal"]))
        story.append(Spacer(1, 10))

    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "Sources: Sentinel-2, Sentinel-1 (ESA), Dynamic World (Google),"
        " WorldCover & WorldCereal (ESA), CHIRPS (UCSB), SoilGrids "
        "(ISRIC), Soil Health Card scheme, Karnataka crop survey, "
        "Livestock Census 2019, Agmarknet. Generated by "
        f"{APP_NAME} for {COMPANY}.",
        ParagraphStyle("foot", fontSize=7, textColor=colors.grey)))

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=1.8 * cm, rightMargin=1.8 * cm,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        title="Ground Intel - Area Report",
    )
    doc.build(story)

    return buf.getvalue()
