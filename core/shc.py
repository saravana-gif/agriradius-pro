"""Soil Health Card (SHC) measured nutrient status + fertiliser guidance.

Unlike SoilGrids (modelled 250 m estimates), this is MEASURED data:
district-level aggregation of lab-tested farmer soil samples from the
Government of India's Soil Health Card scheme (soilhealth.dac.gov.in
Nutrient Dashboard, RKVY soil health & fertility scheme cycles).

Bundled file: data/reference/shc_district_nutrients.csv
  One row per district for the latest complete cycle. Percentages of
  tested samples per class:
    n/p/k/oc  -> low / med / high
    ph        -> acid / neut / alk
    ec_saline -> % saline
    *_def     -> % samples DEFICIENT for S, Fe, Zn, Cu, B, Mn

Refresh path: the portal's public GraphQL endpoint
(soilhealth4.dac.gov.in, operation GetNutrientDashboardForPortal)
returns the same aggregates; re-pull per cycle and regenerate the CSV.

Fertiliser guidance below follows the standard soil-test-based
package-of-practices rule (ICAR/STCR general recommendation): apply
the crop's recommended dose, +25% when the soil test class is Low and
-25% when High. These are ESTIMATES for planning - final doses should
come from the farmer's own SHC / local KVK.
"""

from functools import lru_cache

import pandas as pd

from config import PROJECT_ROOT

SHC_CSV = PROJECT_ROOT / "data" / "reference" / "shc_district_nutrients.csv"

# Display metadata for the three-class macro nutrients
MACROS = {
    "n": "Nitrogen (N)",
    "p": "Phosphorus (P)",
    "k": "Potassium (K)",
    "oc": "Organic Carbon",
}

MICROS = {
    "zn_def": "Zinc (Zn)",
    "b_def": "Boron (B)",
    "fe_def": "Iron (Fe)",
    "s_def": "Sulphur (S)",
    "mn_def": "Manganese (Mn)",
    "cu_def": "Copper (Cu)",
}

# What to do about a widely deficient micronutrient (generic ICAR-style
# advisories - amounts vary by crop/soil; confirm with KVK).
MICRO_ADVICE = {
    "zn_def": "Zinc sulphate ~25 kg/ha basal once in 2-3 seasons",
    "b_def": "Borax ~10 kg/ha basal (do not exceed - narrow safe range)",
    "fe_def": "Foliar FeSO4 0.5-1% sprays (soil doses ineffective in "
              "alkaline soil)",
    "s_def": "Gypsum ~200 kg/ha or S-containing fertilisers (SSP)",
    "mn_def": "Foliar MnSO4 0.5% spray at active growth",
    "cu_def": "CuSO4 only if local test confirms (rarely needed)",
}

# Typical recommended fertiliser doses (package of practices, KA/TN
# blend). kg/ha N : P2O5 : K2O for field crops; per-plant grams for
# coconut & banana. APPROXIMATE - varieties & irrigation change these.
RDF = {
    "Coconut (per palm/yr)": {"unit": "g/palm", "n": 500, "p": 320, "k": 1200},
    "Banana (per plant/yr)": {"unit": "g/plant", "n": 200, "p": 100, "k": 300},
    "Paddy": {"unit": "kg/ha", "n": 100, "p": 50, "k": 50},
    "Maize": {"unit": "kg/ha", "n": 100, "p": 50, "k": 25},
    "Ragi": {"unit": "kg/ha", "n": 50, "p": 40, "k": 25},
    "Turmeric": {"unit": "kg/ha", "n": 125, "p": 60, "k": 108},
    "Ginger": {"unit": "kg/ha", "n": 75, "p": 50, "k": 50},
    "Chilli (irrigated)": {"unit": "kg/ha", "n": 100, "p": 50, "k": 50},
    "Groundnut": {"unit": "kg/ha", "n": 25, "p": 50, "k": 25},
    "Sugarcane": {"unit": "kg/ha", "n": 250, "p": 75, "k": 190},
    "Cotton": {"unit": "kg/ha", "n": 80, "p": 40, "k": 40},
}

# Soil-test-class multiplier (Low soils need more, High soils less)
CLASS_FACTOR = {"Low": 1.25, "Medium": 1.0, "High": 0.75}


def has_data():
    return SHC_CSV.exists()


@lru_cache(maxsize=1)
def load():
    """SHC district table with matching keys. Empty df if missing."""
    from core.allied import _norm
    if not SHC_CSV.exists():
        return pd.DataFrame()
    df = pd.read_csv(SHC_CSV)
    df["_key"] = df["district"].map(_norm)
    df["_state"] = df["state"].map(_norm)
    return df


def for_districts(pairs):
    """Rows for [(state, district), ...] with rename tolerance."""
    from core.allied import _norm, DISTRICT_ALIAS
    df = load()
    if df.empty or not pairs:
        return pd.DataFrame()
    out, seen = [], set()
    for state, district in pairs:
        dn = _norm(district)
        dn = DISTRICT_ALIAS.get(dn, dn)
        sub = df[df["_state"] == _norm(state)]
        if sub.empty:
            sub = df
        hit = sub[sub["_key"] == dn]
        if hit.empty:
            import difflib
            close = difflib.get_close_matches(
                dn, sub["_key"].tolist(), n=1, cutoff=0.82)
            if close:
                hit = sub[sub["_key"] == close[0]]
        if not hit.empty and hit.iloc[0]["_key"] not in seen:
            seen.add(hit.iloc[0]["_key"])
            out.append(hit.iloc[0])
    return pd.DataFrame(out).reset_index(drop=True) if out \
        else pd.DataFrame()


def area_summary(rows):
    """Sample-weighted summary across the district rows in view.

    Returns dict:
      cycle, samples,
      macros: {key: {label, low, med, high, dominant}}
      ph: {acid, neut, alk, dominant}
      ec_saline,
      micros: {key: {label, deficient_pct, advice}}
    """
    if rows is None or len(rows) == 0:
        return None
    w = rows["samples"].astype(float).clip(lower=1)

    def wavg(col):
        return float((rows[col].astype(float) * w).sum() / w.sum())

    macros = {}
    for key, label in MACROS.items():
        low, med, high = (round(wavg(f"{key}_low")),
                          round(wavg(f"{key}_med")),
                          round(wavg(f"{key}_high")))
        dom = max([("Low", low), ("Medium", med), ("High", high)],
                  key=lambda t: t[1])[0]
        macros[key] = {"label": label, "low": low, "med": med,
                       "high": high, "dominant": dom}

    acid, neut, alk = (round(wavg("ph_acid")), round(wavg("ph_neut")),
                       round(wavg("ph_alk")))
    ph_dom = max([("Acidic", acid), ("Neutral", neut),
                  ("Alkaline", alk)], key=lambda t: t[1])[0]

    micros = {}
    for key, label in MICROS.items():
        pct = round(wavg(key))
        micros[key] = {"label": label, "deficient_pct": pct,
                       "advice": MICRO_ADVICE.get(key, "")}

    return {
        "cycle": str(rows.iloc[0]["cycle"]),
        "samples": int(rows["samples"].sum()),
        "districts": [f"{r['district'].title()} ({r['state'].title()})"
                      for _, r in rows.iterrows()],
        "macros": macros,
        "ph": {"acid": acid, "neut": neut, "alk": alk,
               "dominant": ph_dom},
        "ec_saline": round(wavg("ec_saline")),
        "micros": micros,
    }


def fertilizer_guidance(summary, crop):
    """Soil-test-adjusted dose for `crop` given the area summary.

    Returns dict: unit, rows [{nutrient, rdf, factor, adjusted,
    soil_class}], notes [str].
    """
    if summary is None or crop not in RDF:
        return None
    base = RDF[crop]
    nutmap = {"n": "n", "p": "p", "k": "k"}
    out_rows = []
    for nk in ("n", "p", "k"):
        cls = summary["macros"][nutmap[nk]]["dominant"]
        factor = CLASS_FACTOR.get(cls, 1.0)
        rdf = base[nk]
        out_rows.append({
            "nutrient": {"n": "N", "p": "P2O5", "k": "K2O"}[nk],
            "soil_class": cls,
            "rdf": rdf,
            "factor": factor,
            "adjusted": round(rdf * factor),
        })

    notes = []
    # OC low -> organic matter push
    if summary["macros"]["oc"]["dominant"] == "Low":
        notes.append(
            "Organic carbon is LOW in most samples - add FYM/compost "
            "(5-10 t/ha) or green manure; it improves every other "
            "nutrient's availability.")
    # top micronutrient issues (>= 40% samples deficient)
    for key, m in summary["micros"].items():
        if m["deficient_pct"] >= 40:
            notes.append(
                f"{m['label']}: {m['deficient_pct']}% of samples "
                f"deficient - {m['advice']}.")
    if summary["ph"]["dominant"] == "Acidic":
        notes.append("Soils trend ACIDIC - liming may be advised; "
                     "avoid over-applying acidifying fertilisers.")
    if summary["ph"]["dominant"] == "Alkaline":
        notes.append("Soils trend ALKALINE - prefer sulphate forms; "
                     "foliar routes work better for Fe/Zn.")
    return {"unit": base["unit"], "rows": out_rows, "notes": notes}


def crops():
    return list(RDF.keys())
