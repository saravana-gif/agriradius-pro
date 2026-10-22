"""Alert rules: TOML in, (fired, trace) out. No eval, ever.

Rules live in rules/rules.toml. A condition is [feature, op, value]
with op one of < <= > >= == != in not_in; value is a literal. A rule
fires when every `all` condition holds and, if it has an `any` list,
at least one of those does. A condition on a missing (None) feature is
false, so missing data never fires an alert.

Farmer-facing drafts are linted (see lint_text): "conditions favour",
"scout before spraying" for pests and diseases, odds not certainty, no
brand / product / OneRoot price, and a cited source. A rule that fails
validation is skipped by the job and reported - never half-applied.

    python -m core.rules        # validate rules/rules.toml
"""

import hashlib
import json
import operator
import re
import string
import sys
import tomllib
from dataclasses import dataclass, field

from config import PROJECT_ROOT

RULES_PATH = PROJECT_ROOT / "rules" / "rules.toml"

SEVERITY_RANK = {"red": 3, "amber": 2, "green": 1}
KINDS = {"weather", "pest", "disease", "harvest"}

OPS = {
    "<": operator.lt, "<=": operator.le, ">": operator.gt,
    ">=": operator.ge, "==": operator.eq, "!=": operator.ne,
    "in": lambda a, b: a in b, "not_in": lambda a, b: a not in b,
}

RULE_KEYS = {
    "id", "title", "kind", "severity", "group", "crops", "months",
    "std_weeks", "dates", "all", "any", "cooldown_days", "priority",
    "approved_by", "approved_on", "source", "draft_en", "template",
    "notes", "verify", "verify_any",
}
REQUIRED = {"id", "title", "kind", "severity", "draft_en", "source"}

# Farmer-facing text must not name brands, products or prices. Brands
# and active ingredients most often pushed at KA/TN input shops; extend
# as needed (lower case, matched as whole words).
BANNED_TERMS = [
    "oneroot", "bayer", "syngenta", "upl", "dhanuka", "fmc", "basf",
    "corteva", "rallis", "coromandel", "iffco", "adama", "nagarjuna",
    "confidor", "coragen", "regent", "tracer", "delegate", "amistar",
    "nativo", "folicur", "ridomil", "contaf", "imidacloprid", "fipronil",
    "spinetoram", "spinosad", "chlorantraniliprole", "emamectin",
    "thiamethoxam", "propiconazole", "hexaconazole", "mancozeb",
    "carbendazim", "tebuconazole", "azoxystrobin", "metalaxyl",
    "cypermethrin", "chlorpyrifos", "acephate", "price", "rupee",
    "rupees",
]
_BANNED_RE = re.compile(r"\b(" + "|".join(map(re.escape, BANNED_TERMS))
                        + r")\b|₹|\brs\.?\s*\d", re.I)
# Odds, not certainty. "I will / we will" (the officer's own promise,
# e.g. "I will check again tomorrow") is allowed; Kannada and Tamil
# words for "definitely / surely" are not.
_CERTAIN_RE = re.compile(r"(?<!\bI )(?<!\bwe )\b(will|certain(ly)?|"
                         r"guarantee[ds]?|definitely|surely|100\s*%)\b"
                         r"|ಖಂಡಿತ|ಖಚಿತವಾಗಿ|ನಿಶ್ಚಿತ|நிச்சயம்|உறுதியாக", re.I)


# The phrases every farmer text must carry, per language.
LINT_PHRASES = {
    "en": ("conditions favour", "scout before spraying"),
    "kn": ("ಅನುಕೂಲ", "ಸಿಂಪಡಿಸುವ ಮೊದಲು"),
    "ta": ("சாதகமா", "தெளிப்பதற்கு முன்"),
}


class RuleError(ValueError):
    pass


@dataclass
class Rule:
    id: str
    title: str
    kind: str
    severity: str
    draft_en: str
    source: str
    group: str = ""
    crops: list = field(default_factory=list)
    months: list = field(default_factory=list)
    std_weeks: list = field(default_factory=list)
    dates: list = field(default_factory=list)       # ["MM-DD", "MM-DD"]
    all: list = field(default_factory=list)
    any: list = field(default_factory=list)
    # How to check afterwards, against OBSERVED data (jobs/verify.py):
    # same [feature, op, value] form on obs_* features. Empty = can only
    # be scored by the officers' 7-day check-back.
    verify: list = field(default_factory=list)
    verify_any: list = field(default_factory=list)
    cooldown_days: int = 7
    priority: int = 0
    approved_by: str = ""
    approved_on: str = ""
    template: str = ""
    notes: str = ""
    hash: str = ""

    @property
    def key(self):
        """Cooldown / one-per-day key: the group, else the rule id."""
        return self.group or self.id

    @property
    def approved(self):
        return bool(self.approved_by.strip())

    def active_on(self, d):
        if self.months and d.month not in self.months:
            return False
        if self.std_weeks:
            from core.features import std_week
            if std_week(d) not in self.std_weeks:
                return False
        if self.dates:
            start, end = self.dates
            md = d.strftime("%m-%d")
            inside = (start <= md <= end) if start <= end else (
                md >= start or md <= end)          # wraps the new year
            if not inside:
                return False
        return True

    def applies_to(self, crop):
        """crop '' = the whole village (rules with no crops)."""
        return (crop in self.crops) if self.crops else crop == ""


def _check_cond(c, rid):
    if (not isinstance(c, list) or len(c) != 3
            or not isinstance(c[0], str) or c[1] not in OPS):
        raise RuleError(f"{rid}: condition {c!r} must be "
                        f"[feature, op, value] with op in {sorted(OPS)}")
    if c[1] in ("in", "not_in") and not isinstance(c[2], list):
        raise RuleError(f"{rid}: {c[1]} needs a list value")
    if isinstance(c[2], dict):
        raise RuleError(f"{rid}: value must be a literal")


def slots(text):
    """Placeholder names in a draft; only plain {name} is allowed."""
    out = []
    for _, name, spec, conv in string.Formatter().parse(text):
        if name is None:
            continue
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name) or spec or conv:
            raise RuleError(f"placeholder {{{name}}} not allowed - use "
                            "plain {feature_name}")
        out.append(name)
    return out


def lint_text(text, kind, lang="en"):
    """Problems with a farmer-facing text (empty list = fine)."""
    probs = []
    low = text.lower()
    favour, scout = LINT_PHRASES[lang]
    if favour not in low:
        probs.append(f'must say "{favour} ..." (conditions favour)')
    if kind in ("pest", "disease") and scout not in low:
        probs.append(f'pest/disease text must say "{scout}" (scout '
                     'before spraying)')
    if _CERTAIN_RE.search(text):
        probs.append("certainty wording (will / certain / guaranteed "
                     "...) - state odds instead")
    m = _BANNED_RE.search(text)
    if m:
        probs.append(f"brand / product / price term: {m.group(0)!r}")
    return probs


def _parse(raw):
    unknown = set(raw) - RULE_KEYS
    rid = raw.get("id", "?")
    if unknown:
        raise RuleError(f"{rid}: unknown keys {sorted(unknown)}")
    missing = REQUIRED - set(raw)
    if missing:
        raise RuleError(f"{rid}: missing {sorted(missing)}")
    if raw["severity"] not in SEVERITY_RANK:
        raise RuleError(f"{rid}: severity must be red/amber/green")
    if raw["kind"] not in KINDS:
        raise RuleError(f"{rid}: kind must be one of {sorted(KINDS)}")
    for c in (raw.get("all", []) + raw.get("any", [])
              + raw.get("verify", []) + raw.get("verify_any", [])):
        _check_cond(c, rid)
    for c in raw.get("verify", []) + raw.get("verify_any", []):
        if not c[0].startswith("obs_"):
            raise RuleError(f"{rid}: verify conditions test observed "
                            f"features (obs_...), not {c[0]!r}")
    if not raw.get("all") and not raw.get("any"):
        raise RuleError(f"{rid}: needs `all` or `any` conditions")
    d = raw.get("dates")
    if d and (len(d) != 2 or not all(
            re.fullmatch(r"\d\d-\d\d", x) for x in d)):
        raise RuleError(f"{rid}: dates must be ['MM-DD', 'MM-DD']")
    if not str(raw["source"]).strip():
        raise RuleError(f"{rid}: source must be cited")
    slots(raw["draft_en"])
    probs = lint_text(raw["draft_en"], raw["kind"])
    if probs:
        raise RuleError(f"{rid}: draft_en - " + "; ".join(probs))
    r = Rule(**{k: v for k, v in raw.items()})
    r.crops = [c.lower() for c in r.crops]
    r.hash = hashlib.sha1(json.dumps(raw, sort_keys=True).encode()
                          ).hexdigest()[:10]
    return r


def load(path=None):
    """(rules, errors). A bad rule is left out and named in errors."""
    path = path or RULES_PATH
    with open(path, "rb") as f:
        doc = tomllib.load(f)
    rules, errors, seen = [], [], set()
    for raw in doc.get("rule", []):
        try:
            r = _parse(raw)
            if r.id in seen:
                raise RuleError(f"{r.id}: duplicate id")
            seen.add(r.id)
            rules.append(r)
        except (RuleError, TypeError) as e:
            errors.append(str(e))
    return rules, errors


def check_outcome(rule, obs):
    """Did what the rule warned about happen? Returns (outcome, trace):
    outcome 'hit' / 'false_alarm', or None while any needed observation
    is still missing (never guessed)."""
    conds = rule.verify + rule.verify_any
    if not conds:
        return None, {}
    if any(obs.get(c[0]) is None for c in conds):
        return None, {}
    probe = Rule(id=rule.id, title="", kind=rule.kind, severity="green",
                 draft_en="", source="", all=rule.verify,
                 any=rule.verify_any)
    ok, trace = evaluate(probe, obs)
    return ("hit" if ok else "false_alarm"), trace


def evaluate(rule, feats):
    """(fired, trace). trace = [[feature, op, value, actual, ok]]."""
    def check(c):
        name, op, val = c
        actual = feats.get(name)
        if actual is None:
            ok = False
        else:
            try:
                ok = bool(OPS[op](actual, val))
            except TypeError:
                ok = False
        return [name, op, val, actual, ok]

    t_all = [check(c) for c in rule.all]
    t_any = [check(c) for c in rule.any]
    fired = all(t[4] for t in t_all) and (
        not t_any or any(t[4] for t in t_any))
    return fired, {"all": t_all, "any": t_any}


def fmt_value(name, v):
    if v is None:
        return "n/a"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, float)):
        if name.endswith("_pct"):
            return f"{v:+.0f}%"
        if isinstance(v, float) and abs(v) < 10 and v != int(v):
            return f"{v:.1f}"
        return f"{v:.0f}"
    return str(v)


def render(text, feats):
    """Fill {slots} from features (formatted, missing -> 'n/a')."""
    return text.format_map({n: fmt_value(n, feats.get(n))
                            for n in slots(text)})


def main():
    rules, errors = load()
    for r in rules:
        state = (f"approved by {r.approved_by}" if r.approved
                 else "DRAFT (English only, not shareable)")
        print(f"ok  {r.id:28s} {r.severity:5s} {state}")
    for e in errors:
        print(f"ERR {e}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
