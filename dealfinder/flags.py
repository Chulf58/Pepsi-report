"""Good-offer flags and the notification text (ruling
report-flags-good-offers-fixed-limit-then-below-average).

An offer is flagged when it is valid now, is a confirmed Pepsi Max or Cult Energy row (not
a "variants, Max likely" row, not next week's price) and either its kr/L is under the fixed
limit for its product, or, once 4 weeks of history give a 12-week average, it is at least
the configured percentage below that average. The limits live in data/products.json under
"good_offer"; without that key nothing is flagged.
"""

import json
from dataclasses import dataclass, field

CONFIG_KEY = "good_offer"


@dataclass(frozen=True)
class Limits:
    # Product name -> kr/L the price must be under.
    fixed: dict = field(default_factory=dict)
    # Percent below the 12-week average that counts; None switches the rule off.
    below_average_percent: float | None = None


def _positive_number(value, what, path):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not value > 0:
        raise ValueError("%s: %s must be a positive number" % (path, what))
    return float(value)


def load_limits(path):
    with open(path, encoding="utf-8") as f:
        config = json.load(f).get(CONFIG_KEY, {})
    if not isinstance(config, dict):
        raise ValueError("%s: %r must be an object" % (path, CONFIG_KEY))
    fixed = config.get("max_kr_per_l", {})
    if not isinstance(fixed, dict):
        raise ValueError("%s: %s/max_kr_per_l must map product names to numbers" % (path, CONFIG_KEY))
    fixed = {p: _positive_number(v, "%s/max_kr_per_l/%s" % (CONFIG_KEY, p), path)
             for p, v in fixed.items()}
    pct = config.get("below_average_percent")
    if pct is not None:
        pct = _positive_number(pct, "%s/below_average_percent" % CONFIG_KEY, path)
    return Limits(fixed, pct)


def flag_reason(o, note, base, limits, today):
    """Why this listed offer is a good offer, or '' when it is not."""
    if note or not o.valid_from <= today.isoformat():
        return ""
    reasons = []
    limit = limits.fixed.get(o.product)
    if limit is not None and o.kr_per_l < limit:
        reasons.append("under %g kr/L" % limit)
    pct = limits.below_average_percent
    if pct is not None and base and (base.average - o.kr_per_l) / base.average * 100 >= pct - 1e-9:
        reasons.append("%g%% or more below the 12-week average" % pct)
    return "good offer: " + ", ".join(reasons) if reasons else ""


def flagged_offers(listed):
    """The flagged (offer, reason) pairs from listed rows, cheapest first."""
    rows = [(o, flag) for o, _vs, _base, _note, flag in listed if flag]
    return sorted(rows, key=lambda t: (t[0].kr_per_l, t[0].product, t[0].store))


def toast_text(flagged):
    """'2 good offers: 365discount 9.47, Løvbjerg 10.10', or 'no good offers'."""
    if not flagged:
        return "no good offers"
    names = ", ".join("%s %.2f" % (o.store, o.kr_per_l) for o, _ in flagged)
    return "%d good offer%s: %s" % (len(flagged), "" if len(flagged) == 1 else "s", names)
