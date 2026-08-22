"""Answer questions from the figures this app has already computed.

WHY IT IS NOT A CHATBOT
-----------------------
Fyllo's Dharti is a language model over live sensor data, gated
behind buying their hardware. This is deliberately something else: a
lookup over the numbers already on screen for the selected area. It
does not generate prose about farming, it does not reason about
agronomy, and it never invents a figure.

That constraint is the feature. Every answer here can name the tab
it came from, so a field officer can check it - and when the app has
not measured something, the honest answer is "not measured yet, run
X", not a plausible sentence.

The app has thirteen tabs and a report with 25 sections. Most people
will not read them. This turns "what is the irrigated area here?"
into one line without asking anyone to hunt.
"""

import re

# question intent -> (session-state path, label, unit, which tab,
#                     what to run if missing)
FACTS = [
    {
        "id": "cropland",
        "words": ["cropland", "crop land", "farmland area",
                  "how much farm"],
        "get": lambda s: _dig(s, "irrigation_stats", "cropland_ac"),
        "label": "Cropland in this circle", "unit": "ac",
        "tab": "Irrigation", "run": "Measure irrigated area (satellite)",
    },
    {
        "id": "agriculture",
        "words": ["agriculture", "land cover", "total area"],
        "get": lambda s: _landcover(s, "agriculture"),
        "label": "Agriculture (Dynamic World land cover)", "unit": "ac",
        "tab": "Summary", "run": "Analyze This Area",
    },
    {
        "id": "irrigated",
        "words": ["irrigated", "irrigation area", "summer green",
                  "how much irrigated"],
        "get": lambda s: _dig(s, "irrigation_stats", "summer_green_ac"),
        "label": "Irrigated cropland (Feb-May green and moist)",
        "unit": "ac",
        "tab": "Irrigation", "run": "Measure irrigated area (satellite)",
    },
    {
        "id": "borewell",
        "words": ["borewell", "bore well", "groundwater", "canal",
                  "water source", "where does the water"],
        "get": lambda s: _dig(s, "irrigation_stats",
                              "groundwater_fed_ac"),
        "label": "Irrigated land inferred borewell-fed", "unit": "ac",
        "tab": "Irrigation", "run": "Measure irrigated area (satellite)",
    },
    {
        "id": "plantation_net",
        "words": ["plantation", "tree crop", "net of forest",
                  "coconut area", "arecanut area"],
        "get": lambda s: _dig(s, "forest_stats", "plantation_net_ac"),
        "label": "Plantation net of forest", "unit": "ac",
        "tab": "Forest vs Farmland",
        "run": "Separate forest from plantation here",
    },
    {
        "id": "forest",
        "words": ["forest", "natural forest", "gfc"],
        "get": lambda s: _dig(s, "forest_stats", "forest_ac"),
        "label": "Forest cover (JRC GFC2020)", "unit": "ac",
        "tab": "Forest vs Farmland",
        "run": "Separate forest from plantation here",
    },
    {
        "id": "farmland_trees",
        "words": ["farmland trees", "tree crops not forest"],
        "get": lambda s: _dig(s, "forest_stats", "farmland_trees_ac"),
        "label": "Farmland trees (tree crops, not forest)",
        "unit": "ac",
        "tab": "Forest vs Farmland",
        "run": "Separate forest from plantation here",
    },
    {
        "id": "coconut_survey",
        "words": ["coconut survey", "crop survey", "recorded coconut",
                  "government coconut"],
        "get": lambda s: _dig(s, "coconut_survey", "extent_ac"),
        "label": "Coconut recorded in the government crop survey",
        "unit": "ac",
        "tab": "coconut crop-survey panel under the map",
        "run": "Analyze This Area",
    },
    {
        "id": "parcels",
        "words": ["parcel", "field boundary", "how many fields",
                  "plot size", "field size"],
        "get": lambda s: _dig(s, "parcels_summary", "parcels"),
        "label": "Field parcels detected", "unit": "",
        "tab": "Field Parcels", "run": "Load field parcels",
    },
    {
        "id": "rain",
        "words": ["rain", "rainfall", "monsoon"],
        "get": lambda s: _dig(s, "rain", "mean_annual_mm"),
        "label": "Mean annual rainfall", "unit": "mm",
        "tab": "Rainfall", "run": "Analyze This Area",
    },
]


def _dig(state, key, field):
    d = state.get(key)
    if isinstance(d, dict):
        return d.get(field)
    return None


def _landcover(state, name):
    try:
        for row in (state.get("results") or []):
            if str(row.get("Land Cover", "")).lower() == name:
                return row.get("Area (acres)")
    except Exception:
        pass
    return None


def _norm(q):
    return re.sub(r"[^a-z0-9 ]+", " ", str(q or "").lower())


def _score(q, words):
    n = _norm(q)
    return sum(len(w) for w in words if w in n)


def answer(question, state):
    """Answer from computed figures only. Never invents a number."""
    q = _norm(question)
    if not q.strip():
        return {"kind": "empty",
                "text": "Ask about this area - cropland, irrigation, "
                        "plantation, forest, parcels or rainfall."}

    ranked = sorted(
        ((_score(q, f["words"]), f) for f in FACTS),
        key=lambda x: x[0], reverse=True)
    best, fact = ranked[0]
    if best <= 0:
        return {
            "kind": "unknown",
            "text": ("I only answer from figures this app has "
                     "measured for the selected area - cropland, "
                     "irrigation and its water source, plantation net "
                     "of forest, forest cover, farmland trees, the "
                     "coconut crop survey, field parcels and rainfall. "
                     "I do not give agronomic advice, and I will not "
                     "guess a number that has not been measured."),
        }

    value = fact["get"](state)
    if value is None:
        return {
            "kind": "not_measured", "fact": fact["id"],
            "text": (f"**{fact['label']}** has not been measured for "
                     f"this area yet. Open the **{fact['tab']}** tab "
                     f"and run *{fact['run']}*, then ask again."),
        }

    try:
        v = float(value)
        shown = f"{v:,.0f} {fact['unit']}".strip()
    except (TypeError, ValueError):
        shown = str(value)

    extra = _context(fact["id"], state)
    return {
        "kind": "answer", "fact": fact["id"], "value": value,
        "text": (f"**{fact['label']}: {shown}**"
                 + (f"\n\n{extra}" if extra else "")
                 + f"\n\n*From the {fact['tab']}, for this circle.*"),
    }


def _context(fact_id, state):
    """One line of honest context where the raw number can mislead."""
    irr = state.get("irrigation_stats") or {}

    if fact_id == "irrigated":
        crop = irr.get("cropland_ac")
        val = irr.get("summer_green_ac")
        if crop and val:
            pct = 100.0 * val / crop
            return (f"That is {pct:.0f}% of the cropland here. "
                    f"Measured from the February-May window, when "
                    f"nothing stays green without applied water.")

    if fact_id == "borewell":
        surf = irr.get("surface_fed_ac")
        gw = irr.get("groundwater_fed_ac")
        if surf is not None and gw is not None and (surf + gw):
            pct = 100.0 * gw / (surf + gw)
            return (f"About {pct:.0f}% of the irrigated land found "
                    f"here is far from permanent surface water. "
                    f"Borewell land appears on no canal command-area "
                    f"map, so infrastructure data will not find it.")

    if fact_id == "plantation_net":
        fo = state.get("forest_stats") or {}
        gross = fo.get("plantation_gross_ac")
        net = fo.get("plantation_net_ac")
        if gross and net is not None:
            removed = gross - net
            return (f"{removed:,.0f} ac of the {gross:,.0f} ac raw "
                    f"plantation signal was natural forest and has "
                    f"been subtracted.")

    if fact_id == "parcels":
        ps = state.get("parcels_summary") or {}
        med = ps.get("median_ac")
        if med:
            return (f"Median parcel is {med} ac. These are "
                    f"remote-sensing field units, not legal parcels - "
                    f"they carry no survey number.")

    return None


def suggestions(state):
    """Questions worth asking, given what has actually been measured."""
    out = []
    for f in FACTS:
        if f["get"](state) is not None:
            out.append(f"What is the {f['label'].lower()}?")
    return out[:6]
