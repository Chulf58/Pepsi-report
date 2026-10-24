"""The plain-language paragraph at the top of REPORT.md and out/report.html (ruling
report-md-prose-summary-each-run).

Built from fixed templates over the listed rows, so the same run data always gives the same
text. Only confirmed rows are priced: a "variants, Max likely" row is never the best price,
and is mentioned only by that wording.
"""

import re

from .history import percent_vs
from .match import CULT, PEPSI_MAX, VARIANTS_NOTE

MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December")
NO_CULT = "No Cult Energy offers from Danish chains this week."
MAX_LATER = 2


def _join(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _day_month(iso):
    return int(iso[8:10]), int(iso[5:7])


def _dates(isos):
    """'28 and 29 October'; the month is named once per run of days in the same month."""
    parts = [_day_month(i) for i in sorted(set(isos))]
    words = []
    for n, (day, month) in enumerate(parts):
        same_as_next = n + 1 < len(parts) and parts[n + 1][1] == month
        words.append(str(day) if same_as_next else "%d %s" % (day, MONTHS[month - 1]))
    return _join(words)


def _span(start, end):
    """'from 29 to 31 October', 'from 31 October' or 'on 31 October'."""
    if not end:
        return "from " + _dates([start])
    if start == end:
        return "on " + _dates([start])
    (d1, m1), (d2, m2) = _day_month(start), _day_month(end)
    first = str(d1) if m1 == m2 else "%d %s" % (d1, MONTHS[m1 - 1])
    return "from %s to %d %s" % (first, d2, MONTHS[m2 - 1])


def _price(value):
    return "%d" % value if float(value).is_integer() else "%.2f" % value


_PACK = re.compile(r"^(?:(\d+) x )?(\d+(?:\.\d+)?) L")


def _pack(pack):
    """'24 x 0.33 L cans' as '24 x 33 cl'; text in any other shape is used as it is."""
    m = _PACK.match(pack)
    if not m:
        return pack
    cl = "%g cl" % round(float(m.group(2)) * 100, 2)
    return "%s x %s" % (m.group(1), cl) if m.group(1) else cl


def _stores(rows):
    return _join(dict.fromkeys(t[0].store for t in rows))


def _best_now(product, rows, can_price):
    """Sentences for the cheapest rows (ties together): where, pack, price, kr/L, kr/can, end date."""
    sentences = []
    packs = {}
    for t in rows:
        packs.setdefault((t[0].pack, t[0].price_dkk), []).append(t)
    for n, ((pack, price), group) in enumerate(packs.items()):
        o = group[0][0]
        ends = [t[0].valid_to for t in group if t[0].valid_to]
        sentences.append("%s %s: %s for %s kr, which is %.2f kr per liter or %.2f kr per can%s." % (
            "The cheapest %s right now is at" % product if n == 0 else "Also at",
            _stores(group), _pack(pack), _price(price), o.kr_per_l, can_price(o),
            ", until " + _dates(ends) if ends else ""))
    return sentences


def _flagged(rows):
    stores = list(dict.fromkeys(t[0].store for t in rows))
    flagged = list(dict.fromkeys(t[0].store for t in rows if t[4]))
    if len(flagged) == len(stores):
        return ("It is flagged as a good offer." if len(stores) == 1 else
                "Both are flagged as good offers." if len(stores) == 2 else
                "All are flagged as good offers.")
    if not flagged:
        return ("It is not flagged as a good offer." if len(stores) == 1 else
                "Neither is flagged as a good offer." if len(stores) == 2 else
                "None are flagged as good offers.")
    return "Only %s %s flagged as a good offer." % (_join(flagged), "is" if len(flagged) == 1 else "are")


def _later_item(t):
    o = t[0]
    return "%s has %s for %s kr (%.2f kr/L) %s" % (
        o.store, _pack(o.pack), _price(o.price_dkk), o.kr_per_l, _span(o.valid_from, o.valid_to))


def _lowest(rows):
    """The rows tied at the lowest kr/L (to the 2 decimals the report shows)."""
    if not rows:
        return []
    low = min(round(t[0].kr_per_l, 2) for t in rows)
    return [t for t in rows if round(t[0].kr_per_l, 2) == low]


def summary_text(available, later, errors, stale_days, can_price):
    """The summary paragraph.

    available and later are the report's listed rows (offer, vs, baseline, note, flag), each
    sorted by kr/L. stale_days is the age of the last successful collection when it is over
    the limit, else None. can_price gives an offer's kr per can.
    """
    def confirmed(rows, product):
        return [t for t in rows if t[0].product == product and t[3] != VARIANTS_NOTE]

    now, ahead = confirmed(available, PEPSI_MAX), confirmed(later, PEPSI_MAX)
    parts = []
    best = _lowest(now)
    next_rows = []
    if best:
        parts += _best_now(PEPSI_MAX, best, can_price)
        parts.append(_flagged(best))
        best_stores = {t[0].store for t in best}
        next_rows = _lowest([t for t in now if t[0].store not in best_stores
                             and round(t[0].kr_per_l, 2) > round(best[0][0].kr_per_l, 2)])
        if next_rows:
            parts.append("Next is %s at %.2f kr/L." % (_stores(next_rows), next_rows[0][0].kr_per_l))
    else:
        variants = sum(1 for t in available if t[0].product == PEPSI_MAX and t[3] == VARIANTS_NOTE)
        parts.append("No confirmed Pepsi Max offers right now%s." % (
            "; %d listed as '%s' %s not counted" % (variants, VARIANTS_NOTE, "is" if variants == 1 else "are")
            if variants else ""))
    # A later row is worth naming when it beats the next-best price now (or the best, with
    # no second store); otherwise only the single cheapest one is named.
    bar = round((next_rows or best)[0][0].kr_per_l, 2) if (next_rows or best) else None
    beating = [t for t in ahead if bar is None or round(t[0].kr_per_l, 2) < bar]
    picked = (beating or ahead)[:MAX_LATER if beating else 1]
    if picked:
        parts.append("Coming up: %s." % _join(_later_item(t) for t in picked))

    cult_now, cult_later = confirmed(available, CULT), confirmed(later, CULT)
    if cult_now:
        parts += _best_now(CULT, _lowest(cult_now), can_price)
    elif cult_later:
        parts.append("Cult Energy comes later: %s." % _later_item(cult_later[0]))
    else:
        parts.append(NO_CULT)

    sources = list(dict.fromkeys(s for s, _ in errors))
    parts.append("Source errors: %s." % ", ".join(sources) if sources else "All sources answered.")
    if stale_days is not None:
        parts.append("Warning: the last successful collection was %d days ago." % stale_days)
    if best and best[0][2]:
        base = best[0][2]
        pct = percent_vs(best[0][0].kr_per_l, base)
        parts.append("The best Pepsi Max price is %s the 12-week average of %.2f kr/L." % (
            "equal to" if pct == "0%" else "%s %s" % (pct.lstrip("+-"), "below" if pct[0] == "-" else "above"),
            base.average))
    return " ".join(parts)
