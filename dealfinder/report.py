"""out/report.html and out/report.csv."""

import csv
import os
import re
from collections import Counter
from html import escape

from .match import DANISH_CHAIN_NAMES

CSV_HEADER = ["status", "section", "product", "note", "store", "pack", "price_dkk", "kr_per_l",
              "vs_12w_avg", "avg_12w", "low_12w", "valid_from", "valid_to", "campaign",
              "source", "description", "url", "reason"]
# Values this program computes itself ("-12%"); they never carry a formula.
_COMPUTED = frozenset(("vs_12w_avg",))


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


def _offer_rows(section, group):
    return [{"status": "offer", "section": section, "product": o.product, "note": note,
             "store": o.store, "pack": o.pack, "price_dkk": o.price_dkk, "kr_per_l": o.kr_per_l,
             "vs_12w_avg": vs, "avg_12w": base.average if base else "",
             "low_12w": base.low if base else "", "valid_from": o.valid_from,
             "valid_to": o.valid_to, "campaign": "yes" if o.campaign else "no",
             "source": o.source, "description": o.description, "url": o.url, "reason": ""}
            for o, vs, base, note in group]


def rows_for(listed, quarantined, today):
    available, later = split_listed(listed, today)
    rows = _offer_rows(AVAILABLE, available) + _offer_rows(LATER, later)
    for q in quarantined:
        rows.append({"status": "quarantine", "section": "", "product": q.product, "note": "",
                     "store": q.store, "pack": "",
                     "price_dkk": q.price_dkk if q.price_dkk is not None else "",
                     "kr_per_l": "", "vs_12w_avg": "", "avg_12w": "", "low_12w": "",
                     "valid_from": q.valid_from, "valid_to": q.valid_to, "campaign": "",
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
:root { --bg:#fff; --fg:#1b1b1b; --muted:#666; --line:#ddd; --err:#b42318; }
@media (prefers-color-scheme: dark) { :root { --bg:#151515; --fg:#eee; --muted:#aaa; --line:#333; --err:#f97066; } }
body { background:var(--bg); color:var(--fg); font:15px/1.4 system-ui,sans-serif; margin:0; padding:16px; }
h1 { font-size:1.4em; } h2 { font-size:1.15em; margin-top:2em; }
.wrap { overflow-x:auto; } table { border-collapse:collapse; width:100%; }
th, td { border-bottom:1px solid var(--line); padding:6px 8px; text-align:left; vertical-align:top; }
th { cursor:pointer; user-select:none; white-space:nowrap; } td.num { text-align:right; white-space:nowrap; }
.muted { color:var(--muted); } .note { font-style:italic; } .err { color:var(--err); }
"""

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
           "<th>vs 12-wk avg</th><th>12-wk low</th><th>Valid from</th><th>Valid to</th>"
           "<th>Link</th></tr></thead><tbody>"]
    for o, vs, base, note in rows:
        pct_sort = vs.rstrip("%") if vs.rstrip("%").lstrip("+-").isdigit() else "9999"
        out.append("<tr>" + "".join([
            _cell(escape(o.product)
                  + (' <span class="note">(%s)</span>' % escape(note) if note else "")
                  + '<br><span class="muted">%s</span>' % escape(o.description)),
            _cell(escape(o.store) + ("" if o.campaign else ' <span class="muted">(shelf price)</span>')),
            _cell(escape(o.pack)),
            '<td class="num" data-sort="%s">%.2f</td>' % (o.price_dkk, o.price_dkk),
            '<td class="num" data-sort="%s">%.2f</td>' % (o.kr_per_l, o.kr_per_l),
            '<td class="num" data-sort="%s">%s</td>' % (pct_sort, escape(vs)),
            '<td class="num">%s</td>' % ("%.2f" % base.low if base else ""),
            _cell(escape(o.valid_from)), _cell(escape(o.valid_to)), _cell(link_html(o.url)),
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


def write_html(path, run_id, listed, quarantined, errors, summary_lines, text_matched=(),
               today=None, coverage=()):
    available, later = split_listed(listed, today)
    out = ["<!doctype html><html lang=\"da\"><head><meta charset=\"utf-8\">",
           "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
           "<title>Pepsi Max og Cult priser</title><style>%s</style></head><body>" % STYLE,
           "<h1>Pepsi Max and Cult Energy can prices</h1>",
           "<p class=\"muted\">Run %s. Cans only, sorted by kr/L; prices exclude pant. "
           "'vs 12-wk avg' compares with the mean kr/L of the offers seen in the 12 weeks before "
           "this run. Rows marked 'variants, Max likely' "
           "name Pepsi with several variants but not Max and are kept out of the price history. "
           "Click a column to sort.</p>" % escape(run_id)]
    if errors:
        out.append("<h2 class=\"err\">Source errors</h2><ul class=\"err\">")
        out += ["<li>%s: %s</li>" % (escape(s), escape(m)) for s, m in errors]
        out.append("</ul><p>Offers from a failed source are missing from this report.</p>")
    out.append("<ul>%s</ul>" % "".join("<li>%s</li>" % escape(line) for line in summary_lines))
    for (_, title), rows in zip(SECTION_TITLES, (available, later)):
        out.append("<h2>%s</h2>" % title)
        if rows is available and rows:
            out += ["<p>%s</p>" % escape(line) for line in _cheapest_now(available)]
        out += _offers_table(rows) if rows else ["<p>None.</p>"]
    out.append("<h2>Coverage</h2><p class=\"muted\">Rows per chain this run. Source errors are "
               "listed separately above.</p>")
    out += _coverage_table(coverage)
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
    out.append("<script>%s</script></body></html>" % SORT_JS)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))


def write_reports(out_dir, run_id, listed, quarantined, errors, summary_lines, text_matched=(),
                  *, today, coverage=()):
    os.makedirs(out_dir, exist_ok=True)
    html_path = os.path.join(out_dir, "report.html")
    csv_path = os.path.join(out_dir, "report.csv")
    write_html(html_path, run_id, listed, quarantined, errors, summary_lines, text_matched,
               today, coverage)
    write_csv(csv_path, rows_for(listed, quarantined, today))
    return html_path, csv_path
