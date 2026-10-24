"""Command line entry: python3 -m dealfinder [--offline FIXTURE_DIR]."""

import argparse
import os
import sys
from collections import Counter
from datetime import date, datetime, timezone

from .history import NOT_ENOUGH, append_history, baseline, load_history, percent_vs
from .match import CULT, PEPSI_MAX, VARIANTS_NOTE, load_known_ids
from .parse import TZ_NOTE, copenhagen_date
from .pipeline import build
from .report import write_reports
from .sources import FixtureTransport, HttpTransport, fetch_nemlig, fetch_rema, fetch_tjek

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXIT_SOURCE_ERROR = 2


def parse_args(argv):
    p = argparse.ArgumentParser(prog="python3 -m dealfinder", description=__doc__)
    p.add_argument("--offline", metavar="FIXTURE_DIR",
                   help="read saved responses (tjek_pepsi_max.json, tjek_cult.json, "
                        "rema_page_N.json) instead of the network")
    p.add_argument("--history", default=os.path.join(ROOT, "data", "history.csv"))
    p.add_argument("--out", default=os.path.join(ROOT, "out"))
    p.add_argument("--products", default=os.path.join(ROOT, "data", "products.json"),
                   help="confirmed product ids per source (also nemlig's fetch list)")
    p.add_argument("--today", type=date.fromisoformat,
                   help="run date YYYY-MM-DD (default: today in Denmark)")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        known = load_known_ids(args.products)
    except (OSError, ValueError) as e:
        print("Cannot read product id list %s: %s" % (args.products, e), file=sys.stderr)
        return 1
    now = datetime.now(timezone.utc)
    today = args.today or copenhagen_date(now.strftime("%Y-%m-%dT%H:%M:%S%z"))
    run_id = "%sT%s" % (today.isoformat(), now.strftime("%H:%M:%S.%fZ"))
    transport = FixtureTransport(args.offline) if args.offline else HttpTransport()

    tjek_offers, tjek_errors = fetch_tjek(transport)
    rema_products, rema_errors = fetch_rema(transport)
    nemlig_ids = sorted(set().union(*known["nemlig"].values()))
    nemlig_products, nemlig_errors = fetch_nemlig(transport, nemlig_ids)
    outcome = build(tjek_offers, rema_products, today, run_id, nemlig_products, known)
    errors = tjek_errors + rema_errors + nemlig_errors + outcome.row_errors

    prior = load_history(args.history)
    bases = {p: baseline(prior, p, run_id, today) for p in (PEPSI_MAX, CULT)}

    def vs(o):
        base = bases.get(o.product)
        return percent_vs(o.kr_per_l, base) if base else NOT_ENOUGH

    # Variant rows are not confirmed Pepsi Max, so they get no % (ruling
    # pepsi-flere-varianter-rows-listed-probably-max-not-in-history).
    listed = [(o, vs(o), bases.get(o.product), "") for o in outcome.observations]
    listed += [(o, "", bases.get(o.product), VARIANTS_NOTE) for o in outcome.variants]
    # History is written before the report, so a report never shows prices it did not keep.
    append_history(args.history, outcome.observations)

    per_product = Counter(o.product for o in outcome.observations)
    q_product = Counter(q.product or "unknown" for q in outcome.quarantined)
    lines = [
        "Offers kept: %s" % ", ".join("%s: %d" % (p, per_product[p]) for p in (PEPSI_MAX, CULT)),
        "Listed as '%s' (not in history): %d" % (VARIANTS_NOTE, len(outcome.variants)),
        "Bottles dropped: %d" % outcome.bottles_dropped,
        "Out of stock skipped (nemlig): %d" % outcome.out_of_stock,
        "Matched by text, not by a confirmed id: %d" % len(outcome.text_matched),
        "12-week average: %s" % "; ".join(
            "%s %.2f kr/L (low %.2f, %d offers, %d weeks)"
            % (p, b.average, b.low, b.offers, b.weeks) if b else "%s %s" % (p, NOT_ENOUGH)
            for p, b in bases.items()),
        "Quarantined: %d%s" % (len(outcome.quarantined), " (%s)" % ", ".join(
            "%s: %d" % kv for kv in sorted(q_product.items())) if q_product else ""),
        "Rejected Pepsi/Cult rows: %d (%s)" % (sum(outcome.rejected.values()), "; ".join(
            "%s: %d" % kv for kv in outcome.rejected.most_common()) or "none"),
        "Unrelated rows ignored: %d" % outcome.unrelated,
        "Excluded dealers (not Danish chains): %s" % (", ".join(
            "%s %d" % kv for kv in sorted(outcome.excluded_dealers.items())) or "none"),
        "Expired offers skipped: %d" % outcome.expired,
        "Requests: %s" % ", ".join("%s %d" % kv for kv in sorted(transport.counts.items())),
        "Source errors: %s" % ("; ".join("%s: %s" % e for e in errors) if errors else "none"),
    ]
    if TZ_NOTE:
        lines.append("Degraded: " + TZ_NOTE)
    html_path, csv_path = write_reports(args.out, run_id, listed, outcome.quarantined,
                                        errors, lines, outcome.text_matched)
    print("Deal finder run %s%s" % (run_id, " (offline)" if args.offline else ""))
    for line in lines:
        print(line)
    print("History: appended %d rows to %s" % (len(outcome.observations), args.history))
    print("Report: %s, %s" % (html_path, csv_path))
    return EXIT_SOURCE_ERROR if errors else 0
