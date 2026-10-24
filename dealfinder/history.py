"""Append-only price history (data/history.csv) and the 12-week comparison from it.

Ruling report-price-list-with-percent-vs-12-week-average-no-labels: per product, the
12-week average is the mean kr/L over the distinct offers (source plus offer id) stored
in the 12 weeks before the run, the current run left out. With fewer than 4 distinct
weeks of history there is no comparison; the report then shows the lowest price seen so far
and how many weeks that covers.
"""

import csv
import os
import math
import statistics
from dataclasses import asdict, dataclass, fields
from datetime import date, timedelta

NOT_ENOUGH = "not enough history yet"

WINDOW_WEEKS = 12
MIN_WEEKS = 4


@dataclass
class Observation:
    run_id: str
    run_date: str
    product: str
    source: str
    source_id: str
    product_id: str
    store: str
    description: str
    pack: str
    volume_l: float
    price_dkk: float
    kr_per_l: float
    valid_from: str
    valid_to: str
    campaign: bool
    url: str

    def key(self):
        return (self.source, self.source_id, self.price_dkk, self.valid_from)


HEADER = [f.name for f in fields(Observation)]


def dedupe(observations):
    """Keep the first observation per (source, source id, price, valid from) within a run."""
    seen = set()
    out = []
    for o in observations:
        if o.key() not in seen:
            seen.add(o.key())
            out.append(o)
    return out


def load_history(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def append_history(path, observations):
    new_file = not os.path.exists(path) or os.path.getsize(path) == 0
    if not new_file:
        with open(path, encoding="utf-8", newline="") as f:
            header = next(csv.reader(f), [])
        if header != HEADER:
            raise ValueError("%s has columns %s, expected %s; refusing to append"
                             % (path, ",".join(header), ",".join(HEADER)))
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADER)
        if new_file:
            writer.writeheader()
        for o in observations:
            writer.writerow(asdict(o))


@dataclass(frozen=True)
class Baseline:
    average: float
    low: float
    offers: int
    weeks: int


def _window(rows, product, run_id, run_date):
    """(latest kr/L per distinct offer, lowest kr/L over every observation, weeks) in the window."""
    start = run_date - timedelta(weeks=WINDOW_WEEKS)
    offers = {}
    weeks = set()
    low = None
    for r in rows:
        if r["product"] != product or r["run_id"] == run_id:
            continue
        day = date.fromisoformat(r["run_date"])
        if not start < day <= run_date:
            continue
        weeks.add(day.isocalendar()[:2])
        kr = float(r["kr_per_l"])
        # An offer seen in several runs counts once in the average, at its latest stored
        # price; the low looks at every stored price, so a later higher one cannot hide it.
        offers[(r.get("source") or "", r.get("source_id") or "")] = kr
        low = kr if low is None else min(low, kr)
    return offers, low, weeks


def baseline(rows, product, run_id, run_date):
    """The 12-week average and low for product, or None with under 4 weeks of history."""
    offers, low, weeks = _window(rows, product, run_id, run_date)
    if len(weeks) < MIN_WEEKS:
        return None
    return Baseline(round(statistics.fmean(offers.values()), 2), low, len(offers), len(weeks))


def lowest_seen_text(rows, product, run_id, run_date):
    """'lowest seen so far: 8.00 kr/L (1 week sampled)', or None when no week is stored yet."""
    _, low, weeks = _window(rows, product, run_id, run_date)
    if not weeks:
        return None
    n = len(weeks)
    return "lowest seen so far: %.2f kr/L (%d %s sampled)" % (low, n, "week" if n == 1 else "weeks")


def percent_vs(kr_per_l, base):
    """'-12%' or '+5%' against the average, rounded half away from zero; '0%' when equal."""
    pct = round((kr_per_l - base.average) / base.average * 100, 6)  # drop float noise
    whole = int(math.floor(abs(pct) + 0.5))
    if whole == 0:
        return "0%"
    return "%s%d%%" % ("-" if pct < 0 else "+", whole)
