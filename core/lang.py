"""Kannada and Tamil labels for the figures field staff actually use.

SCOPE, DELIBERATELY NARROW
--------------------------
This translates the headline METRIC LABELS and a few short verdict
lines - the words someone standing in a field needs to read a number
off a phone. It does not translate the methodology notes, the data
caveats or the report.

That is a considered limit, not laziness. Those passages carry the
careful distinctions this whole app rests on - "n/a is not zero",
"remote-sensing field units are not legal parcels", "this is a
ceiling, not an estimate". A rough translation of a precise caveat is
worse than an untranslated one: it would read as confident and mean
something slightly different. Those stay in English until a fluent
agronomist reviews them.

Numbers are never translated. 61,233 ac is 61,233 ac in every
language, and digits are what the reader is actually after.
"""

LANGUAGES = {
    "en": "English",
    "kn": "ಕನ್ನಡ (Kannada)",
    "ta": "தமிழ் (Tamil)",
}

# label -> {kn, ta}. English is the key so a missing translation
# falls back to it rather than to a blank.
LABELS = {
    # --- land cover / summary
    "Total Area": {"kn": "ಒಟ್ಟು ವಿಸ್ತೀರ್ಣ", "ta": "மொத்த பரப்பு"},
    "Agriculture": {"kn": "ಕೃಷಿ", "ta": "விவசாயம்"},
    "Trees": {"kn": "ಮರಗಳು", "ta": "மரங்கள்"},
    "Built-up": {"kn": "ಕಟ್ಟಡ ಪ್ರದೇಶ", "ta": "கட்டிடப் பகுதி"},
    "Water": {"kn": "ನೀರು", "ta": "நீர்"},
    "Cropland": {"kn": "ಬೆಳೆ ಭೂಮಿ", "ta": "பயிர் நிலம்"},

    # --- irrigation
    "Net irrigated": {"kn": "ನಿವ್ವಳ ನೀರಾವರಿ",
                      "ta": "நிகர பாசனம்"},
    "Borewell share": {"kn": "ಕೊಳವೆಬಾವಿ ಪಾಲು",
                       "ta": "ஆழ்குழாய் கிணறு பங்கு"},
    "Canal share": {"kn": "ಕಾಲುವೆ ಪಾಲು", "ta": "கால்வாய் பங்கு"},
    "Irrigated - summer green": {
        "kn": "ನೀರಾವರಿ - ಬೇಸಿಗೆ ಹಸಿರು",
        "ta": "பாசனம் - கோடை பசுமை"},
    "Cropland in area": {"kn": "ಈ ಪ್ರದೇಶದ ಬೆಳೆ ಭೂಮಿ",
                         "ta": "இப்பகுதி பயிர் நிலம்"},
    "Borewell-fed (inferred)": {
        "kn": "ಕೊಳವೆಬಾವಿ ಆಧಾರಿತ (ಅಂದಾಜು)",
        "ta": "ஆழ்குழாய் அடிப்படையில் (மதிப்பீடு)"},
    "Canal/tank-fed (inferred)": {
        "kn": "ಕಾಲುವೆ/ಕೆರೆ ಆಧಾರಿತ (ಅಂದಾಜು)",
        "ta": "கால்வாய்/ஏரி அடிப்படையில் (மதிப்பீடு)"},

    # --- forest vs farmland
    "Plantation detected (gross)": {
        "kn": "ಪತ್ತೆಯಾದ ತೋಟ (ಒಟ್ಟು)",
        "ta": "கண்டறியப்பட்ட தோட்டம் (மொத்தம்)"},
    "Forest removed": {"kn": "ಕಾಡು ತೆಗೆದ ನಂತರ",
                       "ta": "காடு நீக்கப்பட்டது"},
    "Plantation NET of forest": {
        "kn": "ಕಾಡು ಹೊರತುಪಡಿಸಿ ತೋಟ",
        "ta": "காடு நீங்கலாக தோட்டம்"},
    "Farmland trees (tree crops)": {
        "kn": "ಕೃಷಿ ಭೂಮಿಯ ಮರಗಳು (ಮರ ಬೆಳೆ)",
        "ta": "விவசாய நில மரங்கள் (மரப் பயிர்)"},
    "Forest cover": {"kn": "ಅರಣ್ಯ ವ್ಯಾಪ್ತಿ", "ta": "காடு பரப்பு"},

    # --- parcels
    "Field parcels": {"kn": "ಜಮೀನು ತುಂಡುಗಳು",
                      "ta": "வயல் துண்டுகள்"},
    "Median parcel size": {"kn": "ಸರಾಸರಿ ತುಂಡಿನ ಗಾತ್ರ",
                           "ta": "இடைநிலை துண்டு அளவு"},
    "Total parcel area": {"kn": "ಒಟ್ಟು ತುಂಡು ವಿಸ್ತೀರ್ಣ",
                          "ta": "மொத்த துண்டு பரப்பு"},
    "Survey number": {"kn": "ಸರ್ವೆ ನಂಬರ್",
                      "ta": "சர்வே எண்"},

    # --- crop cycle / harvest
    "Cropping Pattern": {"kn": "ಬೆಳೆ ಮಾದರಿ",
                         "ta": "பயிர் முறை"},
    "Cycles / Year": {"kn": "ವರ್ಷಕ್ಕೆ ಬೆಳೆ ಸುತ್ತು",
                      "ta": "ஆண்டுக்கு பயிர் சுழற்சி"},
    "Harvest window": {"kn": "ಕೊಯ್ಲು ಸಮಯ",
                       "ta": "அறுவடை காலம்"},
    "Next harvest window": {"kn": "ಮುಂದಿನ ಕೊಯ್ಲು ಸಮಯ",
                            "ta": "அடுத்த அறுவடை காலம்"},

    # --- survey / soil / market
    "Coconut (crop survey)": {"kn": "ತೆಂಗು (ಬೆಳೆ ಸಮೀಕ್ಷೆ)",
                              "ta": "தென்னை (பயிர் கணக்கெடுப்பு)"},
    "Soil pH": {"kn": "ಮಣ್ಣಿನ pH", "ta": "மண் pH"},
    "Organic carbon": {"kn": "ಸಾವಯವ ಇಂಗಾಲ",
                       "ta": "கரிமக் கார்பன்"},
    "Rainfall": {"kn": "ಮಳೆ", "ta": "மழை"},
    "Mandi price": {"kn": "ಮಾರುಕಟ್ಟೆ ದರ",
                    "ta": "சந்தை விலை"},
    "Village": {"kn": "ಗ್ರಾಮ", "ta": "கிராமம்"},
    "District": {"kn": "ಜಿಲ್ಲೆ", "ta": "மாவட்டம்"},
    "Taluk": {"kn": "ತಾಲ್ಲೂಕು", "ta": "தாலுகா"},

    # --- units and short words
    "acres": {"kn": "ಎಕರೆ", "ta": "ஏக்கர்"},
    "ac": {"kn": "ಎಕರೆ", "ta": "ஏக்கர்"},
    "mm": {"kn": "ಮಿ.ಮೀ", "ta": "மி.மீ"},
}

# Short, safe sentences. Anything carrying a precise caveat is
# deliberately NOT here.
PHRASES = {
    "Mostly borewell irrigated": {
        "kn": "ಹೆಚ್ಚಾಗಿ ಕೊಳವೆಬಾವಿ ನೀರಾವರಿ",
        "ta": "பெரும்பாலும் ஆழ்குழாய் பாசனம்"},
    "Mostly canal irrigated": {
        "kn": "ಹೆಚ್ಚಾಗಿ ಕಾಲುವೆ ನೀರಾವರಿ",
        "ta": "பெரும்பாலும் கால்வாய் பாசனம்"},
    "Mostly rain-fed": {
        "kn": "ಹೆಚ್ಚಾಗಿ ಮಳೆ ಆಶ್ರಿತ",
        "ta": "பெரும்பாலும் மழையை நம்பி"},
    "Not measured yet": {
        "kn": "ಇನ್ನೂ ಅಳೆಯಲಾಗಿಲ್ಲ",
        "ta": "இன்னும் அளக்கப்படவில்லை"},
    "Detailed notes are in English": {
        "kn": "ವಿವರವಾದ ಟಿಪ್ಪಣಿಗಳು ಇಂಗ್ಲಿಷ್‌ನಲ್ಲಿವೆ",
        "ta": "விரிவான குறிப்புகள் ஆங்கிலத்தில் உள்ளன"},
}


def current(state=None):
    """Selected language code; English unless chosen otherwise."""
    try:
        if state is not None:
            return state.get("ui_lang", "en") or "en"
        import streamlit as st
        return st.session_state.get("ui_lang", "en") or "en"
    except Exception:
        return "en"


def t(text, lang=None):
    """Translate a known label. Unknown text is returned unchanged.

    Never guesses. An untranslated label appearing in English is a
    visible, harmless gap; a mistranslated one is not.
    """
    lang = lang or current()
    if lang == "en" or not text:
        return text
    key = str(text).strip()
    for table in (LABELS, PHRASES):
        hit = table.get(key)
        if hit and hit.get(lang):
            return hit[lang]
    return text


def bilingual(text, lang=None):
    """'ಕನ್ನಡ (English)' - keeps the English for cross-checking."""
    lang = lang or current()
    if lang == "en":
        return text
    tr = t(text, lang)
    return text if tr == text else f"{tr} ({text})"


def coverage():
    """How much is translated - for the language picker's caption."""
    total = len(LABELS) + len(PHRASES)
    out = {}
    for code in ("kn", "ta"):
        done = sum(1 for tbl in (LABELS, PHRASES)
                   for v in tbl.values() if v.get(code))
        out[code] = (done, total)
    return out
