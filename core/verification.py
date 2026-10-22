"""Verification statistics: how often are we right, with honest error
bars. Pure Python, no I/O, so every number on the accuracy page can be
checked by hand.

Conventions follow the WMO/WWRP forecast-verification literature
(Jolliffe & Stephenson, "Forecast Verification", 2nd ed.) and remote
sensing accuracy assessment (Olofsson et al. 2014, Congalton & Green):

- 2x2 contingency table for yes/no events:
        a = forecast yes, observed yes   (hit)
        b = forecast yes, observed no    (false alarm)
        c = forecast no,  observed yes   (miss)
        d = forecast no,  observed no    (correct negative)
- Confusion matrix rows = reference (truth), columns = predicted.
  Producer's accuracy = recall (how much of the real crop we found);
  user's accuracy = precision (how often a mapped pixel is right).
- Every proportion carries a Wilson 95% interval, which stays sensible
  for small n and for proportions near 0 or 1. Below MIN_N the page
  says "too few to judge" instead of a number.
"""

import math
from collections import Counter

Z95 = 1.959964
MIN_N = 10            # fewer cases than this: no verdict


def wilson(k, n, z=Z95):
    """(low, high) 95% interval for k successes in n trials; (None,
    None) if n == 0."""
    if not n:
        return None, None
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, mid - half), min(1.0, mid + half)


def proportion(k, n):
    """{value, low, high, k, n} for a share, value None if n == 0."""
    lo, hi = wilson(k, n)
    return {"value": (k / n) if n else None, "low": lo, "high": hi,
            "k": k, "n": n}


def _div(x, y):
    return x / y if y else None


# ------------------------------------------------------- yes/no events

def contingency(pairs):
    """pairs: iterable of (forecast_yes: bool, observed_yes: bool)."""
    a = b = c = d = 0
    for f, o in pairs:
        if f and o:
            a += 1
        elif f:
            b += 1
        elif o:
            c += 1
        else:
            d += 1
    return {"a": a, "b": b, "c": c, "d": d}


def categorical_scores(t):
    """Standard scores from a 2x2 table.

    pod   probability of detection = a/(a+c)   (events we caught)
    far   false alarm ratio        = b/(a+b)   (warnings that didn't
                                                verify)
    sr    success ratio            = a/(a+b) = 1 - far
    csi   critical success index   = a/(a+b+c)
    bias  frequency bias           = (a+b)/(a+c)   (>1 over-forecasts)
    hss   Heidke skill score: accuracy relative to random chance with
          the same frequencies; 0 = no skill, 1 = perfect, <0 worse
          than chance.
    """
    a, b, c, d = t["a"], t["b"], t["c"], t["d"]
    n = a + b + c + d
    out = {"n": n, "events": a + c, "warnings": a + b,
           "pod": proportion(a, a + c), "sr": proportion(a, a + b),
           "far": proportion(b, a + b),
           "csi": _div(a, a + b + c), "bias": _div(a + b, a + c),
           "accuracy": proportion(a + d, n)}
    den = (a + c) * (c + d) + (a + b) * (b + d)
    out["hss"] = _div(2 * (a * d - b * c), den)
    return out


def mae(pairs):
    """Mean absolute error and mean error (bias) of (forecast, obs)."""
    pairs = [(f, o) for f, o in pairs if f is not None and o is not None]
    if not pairs:
        return {"n": 0, "mae": None, "me": None}
    n = len(pairs)
    return {"n": n, "mae": sum(abs(f - o) for f, o in pairs) / n,
            "me": sum(f - o for f, o in pairs) / n}


# ------------------------------------------------------ classification

def confusion_matrix(y_true, y_pred, classes=None):
    """(classes, matrix) with matrix[i][j] = count of truth i predicted
    as j."""
    classes = list(classes or sorted(set(y_true) | set(y_pred)))
    idx = {c: i for i, c in enumerate(classes)}
    m = [[0] * len(classes) for _ in classes]
    for t, p in zip(y_true, y_pred):
        m[idx[t]][idx[p]] += 1
    return classes, m


def class_metrics(classes, m):
    """Overall accuracy, Cohen's kappa, balanced accuracy, macro F1 and
    per-class producer's / user's accuracy with Wilson intervals."""
    n = sum(map(sum, m))
    k = len(classes)
    diag = sum(m[i][i] for i in range(k))
    rows = [sum(m[i]) for i in range(k)]
    cols = [sum(m[i][j] for i in range(k)) for j in range(k)]
    pe = sum(rows[i] * cols[i] for i in range(k)) / (n * n) if n else 0
    po = diag / n if n else None
    per = {}
    recalls, f1s = [], []
    for i, c in enumerate(classes):
        prod = proportion(m[i][i], rows[i])
        user = proportion(m[i][i], cols[i])
        f1 = None
        if prod["value"] and user["value"]:
            f1 = 2 * prod["value"] * user["value"] / (
                prod["value"] + user["value"])
        per[c] = {"n": rows[i], "producers": prod, "users": user,
                  "f1": f1, "enough": rows[i] >= MIN_N}
        if rows[i]:
            recalls.append(prod["value"])
            f1s.append(f1 or 0.0)
    return {
        "n": n, "classes": classes, "matrix": m,
        "overall": proportion(diag, n),
        "kappa": ((po - pe) / (1 - pe)) if n and pe < 1 else None,
        "balanced_accuracy": (sum(recalls) / len(recalls)
                              if recalls else None),
        "macro_f1": sum(f1s) / len(f1s) if f1s else None,
        "per_class": per,
    }


def spatial_blocks(points, block_km=5.0):
    """Block id per point: a ~block_km grid cell. Points in one block
    are never split between training and test, so nearby (spatially
    autocorrelated) fields cannot leak into the score."""
    out = []
    for lat, lon in points:
        dlat = block_km / 111.0
        dlon = block_km / (111.0 * max(math.cos(math.radians(lat)), 0.2))
        out.append(f"{math.floor(lat / dlat)}:{math.floor(lon / dlon)}")
    return out


def assign_folds(blocks, labels, k=5):
    """Fold (0..k-1) per point, whole blocks at a time. Blocks are
    dealt largest-first to the fold that currently holds the fewest
    examples of the block's commonest class, which keeps every class
    spread across folds where the data allow it."""
    by_block = {}
    for i, b in enumerate(blocks):
        by_block.setdefault(b, []).append(i)
    fold_counts = [Counter() for _ in range(k)]
    fold_sizes = [0] * k
    fold_of = {}
    order = sorted(by_block, key=lambda b: (-len(by_block[b]), b))
    for b in order:
        idx = by_block[b]
        top = Counter(labels[i] for i in idx).most_common(1)[0][0]
        f = min(range(k), key=lambda j: (fold_counts[j][top],
                                         fold_sizes[j], j))
        fold_of[b] = f
        fold_sizes[f] += len(idx)
        fold_counts[f].update(labels[i] for i in idx)
    return [fold_of[b] for b in blocks]


def verdict_for_rate(p, threshold=0.6):
    """Status of a rule from its share-right proportion dict:
    too_few / retire (95% upper bound below threshold) / watch (point
    estimate below threshold) / ok."""
    if p["n"] < MIN_N:
        return "too_few"
    if p["high"] < threshold:
        return "retire"
    if p["value"] < threshold:
        return "watch"
    return "ok"
