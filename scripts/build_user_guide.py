"""Regenerate the User Guide PDF from the in-app help text.

Single source of truth: ui/help.py GUIDE_MD. Run this whenever the
guide changes so docs/OneRoot_AgriRadius_UserGuide.pdf stays in sync:

    py scripts/build_user_guide.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ui.help import GUIDE_MD          # noqa: E402
from core import data_vintage as dv   # noqa: E402

from reportlab.lib.pagesizes import A4                       # noqa: E402
from reportlab.lib.units import mm                           # noqa: E402
from reportlab.lib import colors                             # noqa: E402
from reportlab.platypus import (SimpleDocTemplate, Paragraph,  # noqa: E402
                                Spacer, HRFlowable, Table, TableStyle)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle  # noqa

GREEN = colors.HexColor("#16A34A")
DARK = colors.HexColor("#0E3D20")
GREY = colors.HexColor("#555555")


def clean(s):
    return "".join(ch for ch in s
                   if ord(ch) < 0x2190 and ord(ch) != 0xfe0f).strip()


def inline(s):
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"\*(.+?)\*", r"<i>\1</i>", s)
    s = re.sub(r"`(.+?)`", r'<font face="Courier">\1</font>', s)
    return s


def build():
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Title"], textColor=DARK,
                        fontSize=20, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=GREEN,
                        fontSize=13, spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=9.5,
                          leading=13, spaceAfter=3)
    bullet = ParagraphStyle("bullet", parent=body, leftIndent=10)
    small = ParagraphStyle("small", parent=body, fontSize=8,
                           textColor=GREY)

    story = [Paragraph("OneRoot AgriRadius Pro", h1),
             Paragraph("New-user operating guide",
                       ParagraphStyle("sub", parent=body,
                                      textColor=GREY, fontSize=10)),
             HRFlowable(width="100%", color=GREEN, thickness=1.2,
                        spaceBefore=6, spaceAfter=8)]

    for raw in GUIDE_MD.strip().splitlines():
        line = raw.rstrip()
        t = clean(line)
        if not t:
            story.append(Spacer(1, 3)); continue
        if line.strip() == "---":
            story.append(HRFlowable(width="100%",
                                    color=colors.HexColor("#cccccc"),
                                    thickness=0.6, spaceBefore=4,
                                    spaceAfter=4)); continue
        if line.startswith("### "):
            continue
        if line.startswith("#### "):
            story.append(Paragraph(inline(clean(line[5:])), h2)); continue
        if line.lstrip().startswith("- "):
            story.append(Paragraph("&bull;&nbsp;"
                                   + inline(clean(line.lstrip()[2:])),
                                   bullet)); continue
        story.append(Paragraph(inline(t), body))

    # Data-vintage table
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", color=GREEN, thickness=1,
                            spaceBefore=4, spaceAfter=6))
    story.append(Paragraph("How current is each data source?", h2))
    story.append(Paragraph(clean(dv.legend()), small))
    story.append(Spacer(1, 4))
    df = dv.as_table()
    data = [["Data source", "As of", "Type"]]
    for _, r in df.iterrows():
        data.append([Paragraph(clean(r["Data"]), small),
                     Paragraph(clean(r["As of"]), small),
                     Paragraph(clean(r["Type"]), small)])
    tbl = Table(data, colWidths=[70 * mm, 60 * mm, 35 * mm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), GREEN),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bbbbbb")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f1f8e9")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "Always read the 'As of' date so you never mistake older "
        "reference data (e.g. the 1960-2018 SLUSI soil survey or the "
        "2019 livestock census) for today's ground reality.", small))

    out = ROOT / "docs" / "OneRoot_AgriRadius_UserGuide.pdf"
    SimpleDocTemplate(
        str(out), pagesize=A4,
        leftMargin=16 * mm, rightMargin=16 * mm,
        topMargin=14 * mm, bottomMargin=14 * mm,
        title="OneRoot AgriRadius Pro - User Guide",
    ).build(story)
    print("Wrote", out)


if __name__ == "__main__":
    build()
