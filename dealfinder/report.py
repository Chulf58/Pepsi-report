"""out/report.html and out/report.csv."""

import csv
import os
import re
from decimal import ROUND_HALF_UP, Decimal
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from html import escape

from .match import DANISH_CHAIN_NAMES
from .summary import summary_text

CSV_HEADER = ["status", "section", "product", "note", "flag", "store", "pack", "price_dkk", "kr_per_l",
              "kr_per_can", "vs_12w_avg", "avg_12w", "low_12w", "valid_from", "valid_to", "campaign",
              "delivery_slot", "source", "description", "url", "reason"]
# Values this program computes itself ("-12%"); they never carry a formula.
_COMPUTED = frozenset(("vs_12w_avg",))


STALE_DAYS = 8


@dataclass
class Extras:
    """Run facts the report shows besides the price rows."""
    coverage: list = field(default_factory=list)
    # {product: {store: {week label: kr/L}}} and the column labels, oldest first.
    weekly: dict = field(default_factory=dict)
    week_labels: list = field(default_factory=list)
    # ISO date of the last successful collection, "" when there is none on record.
    last_success: str = ""
    toast: str = ""


def age_days(extras, today):
    """Days from the last successful collection to the run date, or None with none on record."""
    return (today - date.fromisoformat(extras.last_success)).days if extras.last_success else None


def age_lines(extras, today):
    """Report age and last collection lines; the last one is a warning when over 8 days old."""
    days = age_days(extras, today)
    if days is None:
        return ["Last successful collection: none on record before this run"]
    lines = ["Last successful collection: %s (%d day%s before this run)"
             % (extras.last_success, days, "" if days == 1 else "s")]
    if days > STALE_DAYS:
        lines.append("WARNING: the last successful collection is %d days old (more than %d)"
                     % (days, STALE_DAYS))
    return lines


AVAILABLE, LATER = "available", "later"
SECTION_TITLES = ((AVAILABLE, "Available now"), (LATER, "Starts later"))
NOT_SEEN = "not seen this run"


def split_listed(listed, today):
    """(available now, starts later), each sorted by kr/L; today is the run date in Danish time."""
    def by_price(t):
        return (t[0].kr_per_l, t[0].product)
    now = today.isoformat()
    available = sorted((t for t in listed if t[0].valid_from <= now), key=by_price)
    later = sorted((t for t in listed if t[0].valid_from > now), key=by_price)
    return available, later


def summary_for(listed, errors, today, extras):
    """The plain-language summary paragraph for a run (unescaped)."""
    available, later = split_listed(listed, today)
    days = age_days(extras, today)
    return summary_text(available, later, errors, days if days is not None and days > STALE_DAYS else None,
                        kr_per_can)


def coverage_rows(outcome):
    """Per chain: rows accepted, variants, quarantined and bottles dropped.

    Every allowlisted chain gets a row, so a chain with no row at all can be reported as
    not seen. Chains outside the list (not expected) follow, so no count is lost.
    """
    counters = {"accepted": Counter(o.store.lower() for o in outcome.observations),
                "variants": Counter(o.store.lower() for o in outcome.variants),
                "quarantined": Counter(q.store.lower() for q in outcome.quarantined),
                "bottles": Counter({k.lower(): v for k, v in outcome.bottles_by_store.items()})}
    names = {n.lower(): n for n in DANISH_CHAIN_NAMES}
    for c in counters.values():
        for key in c:
            names.setdefault(key, key)
    rows = []
    for key, name in names.items():
        row = {"chain": name, **{k: c[key] for k, c in counters.items()}}
        row["seen"] = any(row[k] for k in counters)
        rows.append(row)
    return rows


_CAN_COUNT = re.compile(r"^(\d+) x ")


def kr_per_can(o):
    """Price excluding pant divided by the can count in the pack text, rounded half up.

    The history schema has no can count, so it is read from the pack text the pipeline
    writes ("24 x 0.33 L cans", or "0.33 L can" for one). A "2 for 80" row is priced per pack.
    """
    m = _CAN_COUNT.match(o.pack)
    cans = int(m.group(1)) if m else 1
    return float(Decimal(str(o.price_dkk / cans)).quantize(Decimal("0.01"), ROUND_HALF_UP))


def _offer_rows(section, group):
    return [{"status": "offer", "section": section, "product": o.product, "note": note,
             "flag": flag, "store": o.store, "pack": o.pack, "price_dkk": o.price_dkk, "kr_per_l": o.kr_per_l,
             "kr_per_can": kr_per_can(o), "vs_12w_avg": vs, "avg_12w": base.average if base else "",
             "low_12w": base.low if base else "", "valid_from": o.valid_from,
             "valid_to": o.valid_to, "campaign": "yes" if o.campaign else "no",
             "delivery_slot": o.slot, "source": o.source, "description": o.description, "url": o.url, "reason": ""}
            for o, vs, base, note, flag in group]


def rows_for(listed, quarantined, today):
    available, later = split_listed(listed, today)
    rows = _offer_rows(AVAILABLE, available) + _offer_rows(LATER, later)
    for q in quarantined:
        rows.append({"status": "quarantine", "section": "", "product": q.product, "note": "", "flag": "",
                     "store": q.store, "pack": "",
                     "price_dkk": q.price_dkk if q.price_dkk is not None else "",
                     "kr_per_l": "", "kr_per_can": "", "vs_12w_avg": "", "avg_12w": "", "low_12w": "",
                     "valid_from": q.valid_from, "valid_to": q.valid_to, "campaign": "", "delivery_slot": "",
                     "source": q.source, "description": q.description, "url": q.url,
                     "reason": q.reason})
    return rows


_FORMULA = re.compile(r"[\s\x00-\x1f]*[=+\-@]")


def csv_safe(value):
    """Prefix ' to text a spreadsheet could read as a formula.

    That is text starting with a tab, CR or LF, or whose first character after any leading
    whitespace and control characters is =, +, - or @.
    """
    if isinstance(value, str) and (value[:1] in ("\t", "\r", "\n") or _FORMULA.match(value)):
        return "'" + value
    return value


def write_csv(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
        writer.writeheader()
        writer.writerows({k: v if k in _COMPUTED else csv_safe(v) for k, v in row.items()}
                        for row in rows)


def link_html(url):
    """An anchor for an http(s) URL; anything else is shown as escaped text."""
    if not url:
        return ""
    if url.lower().startswith(("http://", "https://")):
        return '<a href="%s" rel="noopener">link</a>' % escape(url)
    return escape(url)


def _cell(value, sort=None):
    attr = ' data-sort="%s"' % escape(str(sort)) if sort is not None else ""
    return "<td%s>%s</td>" % (attr, value)


STYLE = """
:root { --good:#e3f4e1; --bg:#fff; --fg:#1b1b1b; --muted:#666; --line:#ddd; --err:#b42318; }
@media (prefers-color-scheme: dark) { :root { --good:#1d3a22; --bg:#151515; --fg:#eee; --muted:#aaa; --line:#333; --err:#f97066; } }
body { background:var(--bg); color:var(--fg); font:15px/1.4 system-ui,sans-serif; margin:0; padding:16px; }
h1 { font-size:1.4em; } h2 { font-size:1.15em; margin-top:2em; }
.wrap { overflow-x:auto; } table { border-collapse:collapse; width:100%; }
th, td { border-bottom:1px solid var(--line); padding:6px 8px; text-align:left; vertical-align:top; }
th { cursor:pointer; user-select:none; white-space:nowrap; } td.num { text-align:right; white-space:nowrap; }
tr.good td { background:var(--good); }
.muted { color:var(--muted); } .note { font-style:italic; } .err { color:var(--err); }
"""

AGE_JS = """
(function () {
  var el = document.getElementById('age');
  if (!el) return;
  var days = Math.floor((Date.now() - new Date(el.dataset.run + 'T00:00:00').getTime()) / 86400000);
  el.textContent += '. Report age now: ' + days + ' day' + (days === 1 ? '' : 's') +
    (days > %d ? ' - the weekly run looks overdue' : '') + '.';
  if (days > %d) el.className = 'err';
})();
""" % (STALE_DAYS, STALE_DAYS)

SORT_JS = """
document.querySelectorAll('table.sortable').forEach(function (table) {
  table.querySelectorAll('th').forEach(function (th, i) {
    th.addEventListener('click', function () {
      var body = table.tBodies[0], asc = th.dataset.dir !== 'asc';
      th.dataset.dir = asc ? 'asc' : 'desc';
      var key = function (tr) { var c = tr.cells[i]; return c.dataset.sort !== undefined ? c.dataset.sort : c.textContent; };
      var rows = Array.prototype.slice.call(body.rows);
      rows.sort(function (a, b) {
        var x = key(a), y = key(b), nx = parseFloat(x), ny = parseFloat(y);
        var r = (!isNaN(nx) && !isNaN(ny)) ? nx - ny : x.localeCompare(y, 'da');
        return asc ? r : -r;
      });
      rows.forEach(function (tr) { body.appendChild(tr); });
    });
  });
});
"""


def _offers_table(rows):
    out = ["<div class=\"wrap\"><table class=\"sortable\"><thead><tr>"
           "<th>Product</th><th>Store</th><th>Pack</th><th>Price (kr)</th><th>kr/L</th>"
           "<th>kr/can</th><th>vs 12-wk avg</th><th>12-wk low</th><th>Valid from</th><th>Valid to</th>"
           "<th>Flag</th><th>Link</th></tr></thead><tbody>"]
    for o, vs, base, note, flag in rows:
        pct_sort = vs.rstrip("%") if vs.rstrip("%").lstrip("+-").isdigit() else "9999"
        out.append('<tr class="good">' if flag else "<tr>")
        out.append("".join([
            _cell(escape(o.product)
                  + (' <span class="note">(%s)</span>' % escape(note) if note else "")
                  + '<br><span class="muted">%s</span>' % escape(o.description)),
            _cell(escape(o.store) + ("" if o.campaign else ' <span class="muted">(shelf price)</span>')
                  + (' <span class="muted">(delivery slot %s)</span>' % escape(o.slot) if o.slot else "")),
            _cell(escape(o.pack)),
            '<td class="num" data-sort="%s">%.2f</td>' % (o.price_dkk, o.price_dkk),
            '<td class="num" data-sort="%s">%.2f</td>' % (o.kr_per_l, o.kr_per_l),
            '<td class="num" data-sort="%s">%.2f</td>' % (kr_per_can(o), kr_per_can(o)),
            '<td class="num" data-sort="%s">%s</td>' % (pct_sort, escape(vs)),
            '<td class="num">%s</td>' % ("%.2f" % base.low if base else ""),
            _cell(escape(o.valid_from)), _cell(escape(o.valid_to)),
            _cell("<strong>%s</strong>" % escape(flag) if flag else ""),
            _cell(link_html(o.url)),
        ]) + "</tr>")
    out.append("</tbody></table></div>")
    return out


def _cheapest_now(available):
    """One line per product: the cheapest confirmed current price and when it ends."""
    lines = []
    for product in sorted({t[0].product for t in available}):
        # Variant rows are not confirmed Max, so they never stand as the cheapest price.
        rows = [t[0] for t in available if t[0].product == product and not t[3]]
        if rows:
            o = min(rows, key=lambda o: o.kr_per_l)
            lines.append("Cheapest now, %s: %.2f kr/L at %s, %s" % (
                product, o.kr_per_l, o.store,
                "valid to %s" % o.valid_to if o.valid_to else "no end date given"))
    return lines


def _coverage_table(coverage):
    out = ["<div class=\"wrap\"><table class=\"sortable\"><thead><tr><th>Chain</th>"
           "<th>Accepted</th><th>Variants</th><th>Quarantined</th><th>Bottles dropped</th>"
           "</tr></thead><tbody>"]
    for c in coverage:
        if c["seen"]:
            cells = [_cell(escape(c["chain"]))] + [
                '<td class="num">%d</td>' % c[k]
                for k in ("accepted", "variants", "quarantined", "bottles")]
        else:
            cells = [_cell(escape(c["chain"])),
                     '<td colspan="4" class="muted">%s</td>' % NOT_SEEN]
        out.append("<tr>" + "".join(cells) + "</tr>")
    out.append("</tbody></table></div>")
    return out


def _weekly_table(extras):
    """HTML tables of the lowest kr/L per store and ISO week, one per product."""
    out = []
    for product in sorted(extras.weekly):
        stores = extras.weekly[product]
        out.append("<h3>%s</h3>" % escape(product))
        out.append("<div class=\"wrap\"><table><thead><tr><th>Store</th>%s</tr></thead><tbody>"
                   % "".join("<th>%s</th>" % escape(w) for w in extras.week_labels))
        for store in sorted(stores):
            out.append("<tr><td>%s</td>%s</tr>" % (escape(store), "".join(
                '<td class="num">%s</td>' % ("%.2f" % stores[store][w] if w in stores[store] else "")
                for w in extras.week_labels)))
        out.append("</tbody></table></div>")
    return out or ["<p>No history yet.</p>"]


def _md(text):
    """Text for a markdown table cell or line: line breaks become spaces, | and \\ are escaped."""
    flat = re.sub(r"\r\n|\r|\n", " ", str(text))
    return flat.replace("\\", "\\\\").replace("|", "\\|")


def _md_offers(rows):
    out = ["| Product | Store | Pack | kr | kr/L | kr/can | vs avg | From | To | Flag | Slot |",
           "|---|---|---|--:|--:|--:|--:|---|---|---|---|"]
    for o, vs, base, note, flag in rows:
        out.append("| %s | %s | %s | %.2f | %.2f | %.2f | %s | %s | %s | %s | %s |" % (
            _md(o.product + (" (%s)" % note if note else "")), _md(o.store), _md(o.pack),
            o.price_dkk, o.kr_per_l, kr_per_can(o), vs, o.valid_from, o.valid_to or "",
            _md(flag), _md(o.slot)))
    return out


def write_report_md(path, run_id, listed, quarantined, errors, today, extras):
    """REPORT.md: the price list as compact markdown tables, for reading on a phone."""
    available, later = split_listed(listed, today)
    flagged = [(t[0], t[4]) for t in available if t[4]]
    out = ["# Pepsi Max and Cult Energy prices", "", _md(summary_for(listed, errors, today, extras)), "",
           "Run date: %s. Run id: %s." % (today.isoformat(), run_id),
           "Prices exclude pant; kr/L and kr/can are worked out from them.", ""]
    out += ["- " + line for line in age_lines(extras, today)]
    out.append("- Report age: generated on the run date above; if that date is more than %d days "
               "old, the weekly run has missed." % STALE_DAYS)
    if errors:
        out += ["", "## Source errors", ""] + ["- %s: %s" % (_md(s), _md(m)) for s, m in errors]
        out.append("")
        out.append("Offers from a failed source are missing.")
    out += ["", "## Notification", "", _md(extras.toast or "no good offers")]
    out += ["", "## Cheapest now", ""]
    cheapest = _cheapest_now(available)
    out += ["- " + _md(line) for line in cheapest] or ["None."]
    out += ["", "## Good offers", ""]
    out += ["- %s %.2f kr/L, %s (%s)" % (_md(o.store), o.kr_per_l, _md(o.product), _md(flag))
            for o, flag in sorted(flagged, key=lambda t: (t[0].kr_per_l, t[0].store))] or ["None."]
    out += ["", "## Available now", ""] + (_md_offers(available) if available else ["None."])
    out += ["", "## Starts later", ""] + (_md_offers(later) if later else ["None."])
    out += ["", "## Coverage", "", "| Chain | Accepted | Variants | Quarantined | Bottles dropped |",
            "|---|--:|--:|--:|--:|"]
    for c in extras.coverage:
        out.append("| %s | %s |" % (_md(c["chain"]), (
            " | ".join(str(c[k]) for k in ("accepted", "variants", "quarantined", "bottles"))
            if c["seen"] else NOT_SEEN)))
    out += ["", "## Weekly low per store (kr/L)", ""]
    for product in sorted(extras.weekly):
        out += ["### " + product, "", "| Store | " + " | ".join(extras.week_labels) + " |",
                "|---|" + "--:|" * len(extras.week_labels)]
        for store in sorted(extras.weekly[product]):
            cells = extras.weekly[product][store]
            out.append("| %s | %s |" % (_md(store), " | ".join(
                "%.2f" % cells[w] if w in cells else "" for w in extras.week_labels)))
        out.append("")
    if not extras.weekly:
        out.append("No history yet.")
    if quarantined:
        out += ["", "## Quarantined", "", "%d row%s could not be read safely; see out/report.html on the PC."
                % (len(quarantined), "" if len(quarantined) == 1 else "s")]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out).rstrip("\n") + "\n")


def write_html(path, run_id, listed, quarantined, errors, summary_lines, text_matched=(),
               today=None, extras=None):
    available, later = split_listed(listed, today)
    out = ["<!doctype html><html lang=\"da\"><head><meta charset=\"utf-8\">",
           "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
           "<title>Pepsi Max og Cult priser</title><style>%s</style></head><body>" % STYLE,
           "<h1>Pepsi Max and Cult Energy can prices</h1>",
           "<p class=\"summary\">%s</p>" % escape(summary_for(listed, errors, today, extras)),
           "<p class=\"muted\">Run %s. Cans only, sorted by kr/L; prices exclude pant. "
           "'vs 12-wk avg' compares with the mean kr/L of the offers seen in the 12 weeks before "
           "this run. Rows marked 'variants, Max likely' "
           "name Pepsi with several variants but not Max and are kept out of the price history. "
           "Click a column to sort.</p>" % escape(run_id)]
    if errors:
        out.append("<h2 class=\"err\">Source errors</h2><ul class=\"err\">")
        out += ["<li>%s: %s</li>" % (escape(s), escape(m)) for s, m in errors]
        out.append("</ul><p>Offers from a failed source are missing from this report.</p>")
    ages = age_lines(extras, today)
    out.append("<p class=\"%s\" id=\"age\" data-run=\"%s\">%s</p>" % (
        "err" if len(ages) > 1 else "muted", today.isoformat(), escape("; ".join(ages))))
    out.append("<p><strong>%s</strong></p>" % escape(extras.toast or "no good offers"))
    out.append("<ul>%s</ul>" % "".join("<li>%s</li>" % escape(line) for line in summary_lines))
    for (_, title), rows in zip(SECTION_TITLES, (available, later)):
        out.append("<h2>%s</h2>" % title)
        if rows is available and rows:
            out += ["<p>%s</p>" % escape(line) for line in _cheapest_now(available)]
        out += _offers_table(rows) if rows else ["<p>None.</p>"]
    out.append("<h2>Coverage</h2><p class=\"muted\">Rows per chain this run. Source errors are "
               "listed separately above.</p>")
    out += _coverage_table(extras.coverage)
    out.append("<h2>Weekly low per store</h2><p class=\"muted\">Lowest kr/L per store and ISO week "
               "over the last 12 weeks; a blank cell means no price was kept that week.</p>")
    out += _weekly_table(extras)
    out.append("<h2>Quarantine</h2><p class=\"muted\">Rows that look relevant but could not be "
               "read safely. They are not used in the price history.</p>")
    if quarantined:
        out.append("<div class=\"wrap\"><table class=\"sortable\"><thead><tr><th>Product</th>"
                   "<th>Store</th><th>Offer text</th><th>Price (kr)</th><th>Valid</th><th>Reason</th>"
                   "<th>Link</th></tr></thead><tbody>")
        for q in quarantined:
            price = "" if q.price_dkk is None else "%.2f" % q.price_dkk
            out.append("<tr>" + "".join([
                _cell(escape(q.product)), _cell(escape(q.store)), _cell(escape(q.description)),
                '<td class="num">%s</td>' % price,
                _cell(escape("%s to %s" % (q.valid_from, q.valid_to))), _cell(escape(q.reason)),
                _cell(link_html(q.url))]) + "</tr>")
        out.append("</tbody></table></div>")
    else:
        out.append("<p>None.</p>")
    out.append("<h2>Matched by text</h2><p class=\"muted\">Listed rows whose product id is not "
               "yet confirmed in data/products.json. Check them and add the id to lock the match.</p>")
    if text_matched:
        out.append("<div class=\"wrap\"><table class=\"sortable\"><thead><tr><th>Source</th>"
                   "<th>Product id</th><th>Store</th><th>Offer text</th></tr></thead><tbody>")
        for source, pid, store, text in text_matched:
            out.append("<tr>" + "".join(_cell(escape(v)) for v in (source, pid, store, text)) + "</tr>")
        out.append("</tbody></table></div>")
    else:
        out.append("<p>None.</p>")
    out.append("<script>%s%s</script></body></html>" % (SORT_JS, AGE_JS))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))


def write_reports(out_dir, run_id, listed, quarantined, errors, summary_lines, text_matched=(),
                  *, today, extras, report_md=None):
    os.makedirs(out_dir, exist_ok=True)
    html_path = os.path.join(out_dir, "report.html")
    csv_path = os.path.join(out_dir, "report.csv")
    write_html(html_path, run_id, listed, quarantined, errors, summary_lines, text_matched,
               today, extras)
    write_csv(csv_path, rows_for(listed, quarantined, today))
    if report_md:
        write_report_md(report_md, run_id, listed, quarantined, errors, today, extras)
    return html_path, csv_path
