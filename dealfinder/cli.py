"""Command line entry: python3 -m dealfinder [--offline FIXTURE_DIR]."""

import argparse
import os
import sys
from collections import Counter
from datetime import date, datetime, timezone

from .flags import flag_reason, flagged_offers, load_limits, toast_text
from .history import (NOT_ENOUGH, append_history, baseline, load_history, lowest_seen_text,
                      percent_vs, week_labels, weekly_lows)
from .match import CULT, PEPSI_MAX, VARIANTS_NOTE, load_known_ids
from .mobile import write_mobile
from .parse import TZ_NOTE, copenhagen_date
from .pipeline import UPCOMING_NOTE, build
from .report import NOT_SEEN, Extras, age_lines, coverage_rows, write_reports
from .sources import FixtureTransport, HttpTransport, fetch_nemlig_weeks, fetch_rema, fetch_tjek

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
    p.add_argument("--report-md", metavar="PATH",
                   help="where to write the phone report (default: REPORT.md at the repo root; "
                        "none with --offline)")
    p.add_argument("--last-success", metavar="PATH",
                   help="file holding the date of the last run without source errors (default: "
                        "data/last_success.txt; none with --offline)")
    p.add_argument("--mobile-dir", metavar="PATH",
                   help="where to write the phone page index.html with its manifest and icon "
                        "(default: docs/ at the repo root; none with --offline)")
    p.add_argument("--today", type=date.fromisoformat,
                   help="run date YYYY-MM-DD (default: today in Denmark)")
    args = p.parse_args(argv)
    if not args.offline:
        if args.report_md is None:
            args.report_md = os.path.join(ROOT, "REPORT.md")
        if args.last_success is None:
            args.last_success = os.path.join(ROOT, "data", "last_success.txt")
        if args.mobile_dir is None:
            args.mobile_dir = os.path.join(ROOT, "docs")
    return args


def read_last_success(path):
    """The stored date of the last run without source errors, '' when there is no file."""
    if not path or not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as f:
        text = f.read().strip()
    date.fromisoformat(text)
    return text


def main(argv=None):
    args = parse_args(argv)
    try:
        known = load_known_ids(args.products)
        limits = load_limits(args.products)
    except (OSError, ValueError) as e:
        print("Cannot read product id list %s: %s" % (args.products, e), file=sys.stderr)
        return 1
    try:
        last_good = read_last_success(args.last_success)
    except (OSError, ValueError) as e:
        print("Cannot read last success file %s: %s" % (args.last_success, e), file=sys.stderr)
        return 1
    now = datetime.now(timezone.utc)
    today = args.today or copenhagen_date(now.strftime("%Y-%m-%dT%H:%M:%S%z"))
    run_id = "%sT%s" % (today.isoformat(), now.strftime("%H:%M:%S.%fZ"))
    transport = FixtureTransport(args.offline) if args.offline else HttpTransport()

    tjek_offers, tjek_errors = fetch_tjek(transport)
    rema_products, rema_errors = fetch_rema(transport)
    nemlig_ids = sorted(set().union(*known["nemlig"].values()))
    nemlig_passes, nemlig_errors = fetch_nemlig_weeks(transport, nemlig_ids, next_week=True)
    (this_slot, nemlig_products), (next_slot, nemlig_next) = (
        (nemlig_passes + [("", [])] * 2)[:2])
    outcome = build(tjek_offers, rema_products, today, run_id, nemlig_products, known,
                    this_slot, nemlig_next, next_slot)
    coverage = coverage_rows(outcome)
    errors = tjek_errors + rema_errors + nemlig_errors + outcome.row_errors

    prior = load_history(args.history)
    bases = {p: baseline(prior, p, run_id, today) for p in (PEPSI_MAX, CULT)}

    def vs(o):
        base = bases.get(o.product)
        # No % until 4 weeks of history exist; the summary says what is known instead.
        return percent_vs(o.kr_per_l, base) if base else ""

    def history_text(product, base):
        if base:
            return "%s %.2f kr/L (low %.2f, %d offers, %d weeks)" % (
                product, base.average, base.low, base.offers, base.weeks)
        return "%s %s" % (product, lowest_seen_text(prior, product, run_id, today) or NOT_ENOUGH)

    # Variant rows are not confirmed Pepsi Max, so they get no % (ruling
    # pepsi-flere-varianter-rows-listed-probably-max-not-in-history).
    rows = [(o, vs(o), bases.get(o.product), "") for o in outcome.observations]
    rows += [(o, "", bases.get(o.product), VARIANTS_NOTE) for o in outcome.variants]
    rows += [(o, vs(o), bases.get(o.product), UPCOMING_NOTE) for o in outcome.upcoming]
    listed = [(o, v, b, n, flag_reason(o, n, b, limits, today)) for o, v, b, n in rows]
    flagged = flagged_offers(listed)
    toast = toast_text(flagged)
    # History is written before the report, so a report never shows prices it did not keep.
    append_history(args.history, outcome.observations)
    # A run without source errors is a success, even with zero offers. A failed run leaves the
    # stored date alone, so the age keeps counting from the last good run.
    last_success = today.isoformat() if not errors else last_good
    if not errors and args.last_success and last_good != last_success:
        with open(args.last_success, "w", encoding="utf-8", newline="\n") as f:
            f.write(last_success + "\n")
    extras = Extras(coverage, weekly_lows(load_history(args.history), today),
                    week_labels(today), last_success, toast)

    per_product = Counter(o.product for o in outcome.observations)
    q_product = Counter(q.product or "unknown" for q in outcome.quarantined)
    lines = [
        "Offers kept: %s" % ", ".join("%s: %d" % (p, per_product[p]) for p in (PEPSI_MAX, CULT)),
        "Listed as '%s' (not in history): %d" % (VARIANTS_NOTE, len(outcome.variants)),
        "Next week's nemlig prices listed (not in history): %d" % len(outcome.upcoming),
        "Next week's nemlig slot, not counted above: %s" % (", ".join(
            "%s %d" % kv for kv in sorted(outcome.next_week.items()) if kv[1]) or "nothing"),
        "Bottles dropped: %d" % outcome.bottles_dropped,
        "Out of stock skipped (nemlig): %d" % outcome.out_of_stock,
        "Matched by text, not by a confirmed id: %d" % len(outcome.text_matched),
        "12-week average: %s" % "; ".join(history_text(p, b) for p, b in bases.items()),
        "Coverage: %d of %d chains seen; %s: %s" % (
            sum(c["seen"] for c in coverage), len(coverage), NOT_SEEN,
            ", ".join(c["chain"] for c in coverage if not c["seen"]) or "none"),
        "Good offers: %d" % len(flagged),
        "Notification: %s" % toast,
        *age_lines(extras, today),
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
                                        errors, lines, outcome.text_matched,
                                        today=today, extras=extras,
                                        report_md=args.report_md)
    mobile_path = (write_mobile(args.mobile_dir, run_id, listed, outcome.quarantined, errors, today, extras)
                   if args.mobile_dir else None)
    print("Deal finder run %s%s" % (run_id, " (offline)" if args.offline else ""))
    for line in lines:
        print(line)
    print("History: appended %d rows to %s" % (len(outcome.observations), args.history))
    print("Report: %s, %s" % (html_path, csv_path))
    if mobile_path:
        print("Phone page: %s" % mobile_path)
    return EXIT_SOURCE_ERROR if errors else 0
