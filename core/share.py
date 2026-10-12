"""Share kit for one alert: Kannada / Tamil / English text, a PNG card,
a WhatsApp link and a 45-second voice-note script.

    k = kit(alert_row, "kn")       # alert_row: a row of the alert table
    k.shareable, k.why_not         # both rule and language signed?
    k.headline, k.text, k.voice, k.footer
    k.wa_url                       # https://wa.me/?text=... or None
    card_png(k)                    # PNG bytes (DRAFT banner if unsigned)

No WhatsApp API: the app prepares, a person sends. The WhatsApp text
is the advisory only - village, numbers, source - never a farmer's
name or number.

Indic text needs Pillow with libraqm (complex-script shaping) and the
Noto fonts (fonts-noto-core); scripts/setup_lightsail.sh installs and
checks both. Without raqm, Kannada and Tamil cards are refused rather
than drawn with broken letters.
"""

import datetime
import io
import json
import tomllib
import urllib.parse
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from config import PROJECT_ROOT
from core import rules
from core.sources.forecast import ATTRIBUTION

TEMPLATES_PATH = PROJECT_ROOT / "templates" / "advice.toml"
LANGS = ("kn", "ta", "en")
LANG_NAME = {"kn": "ಕನ್ನಡ", "ta": "தமிழ்", "en": "English"}
VOICE_TARGET_S = 45
VOICE_MAX_S = 55
# Speaking rate for a field officer reading aloud, words per second
# (Kannada and Tamil words are longer - agglutinative).
WORDS_PER_S = {"en": 2.3, "kn": 1.6, "ta": 1.6}

SEVERITY_COLOUR = {"red": (185, 28, 28), "amber": (180, 83, 9),
                   "green": (21, 128, 61)}
FONT_DIRS = [Path("/usr/share/fonts/truetype/noto"),
             Path("/usr/share/fonts/opentype/noto"),
             Path("/usr/share/fonts/truetype/dejavu")]
FONT_FILES = {
    "latin": ("NotoSans-{w}.ttf", "DejaVuSans{dw}.ttf"),
    "kn": ("NotoSansKannada-{w}.ttf",),
    "ta": ("NotoSansTamil-{w}.ttf",),
}


class ShareError(RuntimeError):
    pass


@dataclass
class Kit:
    alert_id: str
    lang: str
    severity: str
    headline: str
    text: str
    voice: str
    footer: str
    village: str
    date_label: str
    shareable: bool
    why_not: str
    draft_label: str

    @property
    def message(self):
        """WhatsApp text: headline, advice, source line."""
        return f"*{self.headline}*\n{self.text}\n\n{self.footer}"

    @property
    def wa_url(self):
        if not self.shareable:
            return None
        return "https://wa.me/?text=" + urllib.parse.quote(self.message)

    @property
    def voice_seconds(self):
        return voice_seconds(self.voice, self.lang)


def voice_seconds(text, lang):
    return round(len(text.split()) / WORDS_PER_S[lang])


# ----------------------------------------------------------- templates

def load_templates(path=None):
    """(templates {rule_id: {lang: block}}, labels {lang: {...}},
    errors). Blocks failing the wording lint are dropped and named."""
    with open(path or TEMPLATES_PATH, "rb") as f:
        doc = tomllib.load(f)
    labels = doc.pop("_labels", {})
    rule_kind = {r.id: r.kind for r in rules.load()[0]}
    out, errors = {}, []
    for rid, langs in doc.items():
        for lang, b in langs.items():
            where = f"{rid}.{lang}"
            if lang not in LANGS:
                errors.append(f"{where}: unknown language")
                continue
            missing = {"headline", "text", "voice", "approved_by"} - set(b)
            if missing:
                errors.append(f"{where}: missing {sorted(missing)}")
                continue
            try:
                for k in ("headline", "text", "voice"):
                    rules.slots(b[k])
            except rules.RuleError as e:
                errors.append(f"{where}: {e}")
                continue
            probs = []
            kind = rule_kind.get(rid, "weather")
            for k in ("text", "voice"):
                probs += [f"{k}: {p}" for p in rules.lint_text(b[k], kind,
                                                               lang)]
            if probs:
                errors.append(f"{where}: " + "; ".join(probs))
                continue
            out.setdefault(rid, {})[lang] = b
    return out, labels, errors


def _date_label(iso, lab, lang):
    """'1 Oct' in English, 'ಅಕ್ಟೋಬರ್ 1' / 'அக்டோபர் 1' otherwise."""
    if not iso:
        return None
    d = datetime.date.fromisoformat(iso)
    months = lab.get("months") or []
    if len(months) != 12:
        return f"{d.day} {d:%b}"
    m = months[d.month - 1]
    return f"{d.day} {m}" if lang == "en" else f"{m} {d.day}"


def localise(feats, lang, labels):
    """Copy of the features with label slots in the card's language."""
    lab = labels.get(lang, {})
    f = dict(feats)
    season = f.get("season")
    if season:
        f["season_label"] = lab.get(season, f.get("season_label"))
        f["season_start_label"] = _date_label(
            f.get(f"{season}_start"), lab, lang) or f.get(
            "season_start_label")
    cat = f.get("season_category")
    if cat:
        f["season_category_label"] = lab.get(cat, f.get(
            "season_category_label"))
    return f


def kit(alert, lang, templates=None, labels=None):
    """Share kit for one alert row (dict-like) in one language."""
    if templates is None or labels is None:
        templates, labels, _ = load_templates()
    lab = labels.get(lang, labels.get("en", {}))
    feats = json.loads(alert["features_json"])
    vintage = json.loads(alert.get("vintage_json") or "{}")
    as_of = datetime.date.fromisoformat(alert["as_of"])
    tpl = templates.get(alert["rule_id"], {}).get(lang)

    why = []
    if not str(alert.get("approved_by") or "").strip():
        why.append("rule not signed off (rules/rules.toml approved_by)")
    if tpl is None:
        why.append(f"no approved-format {LANG_NAME[lang]} template")
    elif not str(tpl.get("approved_by") or "").strip():
        why.append(f"{LANG_NAME[lang]} text not signed off "
                   "(templates/advice.toml)")

    if tpl is None:           # fall back to the logged English draft
        lang, lab = "en", labels.get("en", {})
        headline, text = alert["title"], alert["text_en"]
        voice = alert["text_en"]
    else:
        f = localise(feats, lang, labels)
        headline = rules.render(tpl["headline"], f)
        text = rules.render(tpl["text"], f)
        voice = rules.render(tpl["voice"], f)

    parts = [f"{lab.get('source', 'Source')}: {alert['source']}"]
    prov = vintage.get("forecast_provider")
    if prov and any(c[0].startswith("fc_") for c in _conds(alert)):
        parts.append(f"{lab.get('forecast', 'Forecast')}: "
                     f"{ATTRIBUTION.get(prov, prov)}, "
                     f"{vintage.get('forecast_issued_on', '')}")
    parts.append(f"{lab.get('alert', 'Alert')} {alert['alert_id']}")
    return Kit(
        alert_id=alert["alert_id"], lang=lang, severity=alert["severity"],
        headline=headline, text=text, voice=voice,
        footer=" · ".join(parts),
        village=feats.get("village") or alert.get("village_id", ""),
        date_label=f"{_date_label(as_of.isoformat(), lab, lang)} "
                   f"{as_of.year}",
        shareable=not why, why_not="; ".join(why),
        draft_label=lab.get("draft", "DRAFT - do not share"))


def _conds(alert):
    t = json.loads(alert.get("trace_json") or "{}")
    return (t.get("all") or []) + (t.get("any") or [])


# ---------------------------------------------------------------- card

def raqm_ok():
    from PIL import features
    return bool(features.check("raqm"))


@lru_cache(maxsize=None)
def _font_path(key, bold):
    w, dw = ("Bold", "-Bold") if bold else ("Regular", "")
    for pattern in FONT_FILES[key]:
        name = pattern.format(w=w, dw=dw)
        for d in FONT_DIRS:
            if (d / name).exists():
                return str(d / name)
    raise ShareError(f"font for {key} not found - install fonts-noto-core")


@lru_cache(maxsize=64)
def _font(key, size, bold=False):
    from PIL import ImageFont
    layout = (ImageFont.Layout.RAQM if raqm_ok()
              else ImageFont.Layout.BASIC)
    return ImageFont.truetype(_font_path(key, bold), size,
                              layout_engine=layout)


INDIC_BLOCKS = {"kn": (0x0C80, 0x0CFF), "ta": (0x0B80, 0x0BFF)}
JOINERS = {0x200C, 0x200D, 0x0964, 0x0965}     # ZWNJ, ZWJ, dandas


def _runs(text, lang):
    """Split text into (font_key, piece). Kannada/Tamil letters use the
    Indic font; everything else (Latin, digits, punctuation, '·', '°')
    the Latin one - the Indic fonts carry no Latin letters. Spaces stay
    in the run they follow."""
    if lang == "en":
        return [("latin", text)]
    lo, hi = INDIC_BLOCKS[lang]
    out, cur, buf = [], None, ""
    for ch in text:
        o = ord(ch)
        key = lang if (lo <= o <= hi or o in JOINERS) else "latin"
        if ch == " " and cur:
            key = cur
        if key != cur and buf:
            out.append((cur, buf))
            buf = ""
        cur = key
        buf += ch
    if buf:
        out.append((cur, buf))
    return out


def _width(text, lang, size, bold):
    return sum(_font(k, size, bold).getlength(p)
               for k, p in _runs(text, lang))


def _wrap(text, lang, size, bold, max_w):
    lines = []
    for para in text.split("\n"):
        line = ""
        for word in para.split(" "):
            trial = f"{line} {word}".strip()
            if line and _width(trial, lang, size, bold) > max_w:
                lines.append(line)
                line = word
            else:
                line = trial
        lines.append(line)
    return lines


def _draw(draw, xy, text, lang, size, bold, fill):
    """Draw mixed-script text with every run on one baseline."""
    x, y = xy
    base = y + _font("latin", size, bold).getmetrics()[0]
    for k, piece in _runs(text, lang):
        f = _font(k, size, bold)
        draw.text((x, base), piece, font=f, fill=fill, anchor="ls")
        x += f.getlength(piece)


def _fit(text, lang, bold, max_w, max_h, start, smallest, spacing=1.35):
    """Largest font size (and its lines) for which text fits the box."""
    size = start
    while True:
        lines = _wrap(text, lang, size, bold, max_w)
        if len(lines) * size * spacing <= max_h or size <= smallest:
            return size, lines
        size -= 2


def card_png(k, width=1080, height=1350):
    """The share card as PNG bytes (WhatsApp-friendly 4:5)."""
    from PIL import Image, ImageDraw
    if k.lang in ("kn", "ta") and not raqm_ok():
        raise ShareError("Kannada/Tamil cards need Pillow with libraqm "
                         "(apt install libraqm0) - refusing to draw "
                         "broken letters")
    pad = 64
    inner = width - 2 * pad
    img = Image.new("RGB", (width, height), (255, 255, 255))
    d = ImageDraw.Draw(img)
    colour = SEVERITY_COLOUR.get(k.severity, (55, 65, 81))

    hs, hl = _fit(k.headline, k.lang, True, inner, 230, 58, 36, 1.25)
    band = pad + int(len(hl) * hs * 1.25) + pad // 2
    d.rectangle([0, 0, width, band], fill=colour)
    y = pad - 8
    for line in hl:
        _draw(d, (pad, y), line, k.lang, hs, True, (255, 255, 255))
        y += int(hs * 1.25)

    y = band + 28
    if not k.shareable:
        d.rectangle([0, band, width, band + 70], fill=(254, 240, 138))
        _draw(d, (pad, band + 14), k.draft_label, k.lang, 34, True,
              (113, 63, 18))
        y = band + 98
    _draw(d, (pad, y), f"{k.village} · {k.date_label}", k.lang, 34, True,
          (30, 41, 59))
    y += 70

    fs, fl = _fit(k.footer, k.lang, False, inner, 150, 26, 20, 1.3)
    foot_h = int(len(fl) * fs * 1.3)
    body_h = height - y - foot_h - pad - 30
    bs, bl = _fit(k.text, k.lang, False, inner, body_h, 50, 24)
    for line in bl:
        _draw(d, (pad, y), line, k.lang, bs, False, (15, 23, 42))
        y += int(bs * 1.35)

    fy = height - pad - foot_h
    d.line([pad, fy - 18, width - pad, fy - 18], fill=(203, 213, 225),
           width=2)
    for line in fl:
        _draw(d, (pad, fy), line, k.lang, fs, False, (71, 85, 105))
        fy += int(fs * 1.3)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
