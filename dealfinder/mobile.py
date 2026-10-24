"""docs/index.html: the phone page GitHub Pages serves (ruling
phone-report-github-pages-mobile-web-app).

One self-contained file: inline CSS, inline SVG charts and a few lines of inline JS, with no
request to any other host (a Content-Security-Policy meta tag enforces that in the browser).
The only links that leave the page are the offers' own http(s) links. The manifest, icon and
.nojekyll are written next to it so "Add to Home Screen" gives the page an app icon.
"""

import json
import os
from html import escape

from .match import CULT, PEPSI_MAX, VARIANTS_NOTE
from .report import NOT_SEEN, STALE_DAYS, age_days, age_lines, is_web_url, kr_per_can, split_listed, summary_for
from .summary import MONTHS, _pack

PAGE = "index.html"
TITLE = "Pepsi Max & Cult"
CHART_PLACEHOLDER = "The chart appears after 2 weeks of prices."
# Product -> CSS class; the class picks the product's accent colour.
PRODUCTS = ((PEPSI_MAX, "pepsi"), (CULT, "cult"))

MANIFEST = json.dumps({
    "name": "Pepsi Max & Cult prices",
    "short_name": "Pepsi & Cult",
    "start_url": "./",
    "scope": "./",
    "display": "standalone",
    "background_color": "#f4f5f7",
    "theme_color": "#0060c7",
    "icons": [{"src": "icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"}],
}, indent=2) + "\n"

# A can on a rounded square: blue body, grey lid, an orange band for Cult.
ICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
<rect width="512" height="512" rx="112" fill="#0060c7"/>
<rect x="196" y="78" width="120" height="44" rx="16" fill="#d5dbe3"/>
<rect x="172" y="104" width="168" height="320" rx="40" fill="#ffffff"/>
<path d="M172 214c56 -40 112 40 168 0v76c-56 40 -112 -40 -168 0z" fill="#c2410c"/>
<circle cx="256" cy="362" r="26" fill="#0060c7"/>
</svg>
"""

STATIC_FILES = {"manifest.webmanifest": MANIFEST, "icon.svg": ICON, ".nojekyll": ""}

STYLE = """
:root {
  color-scheme: light dark;
  --bg:#f4f5f7; --card:#ffffff; --ink:#14171a; --ink2:#3d4550; --muted:#5b6675; --line:#e2e5ea;
  --pepsi:#0060c7; --cult:#c2410c;
  --good-bg:#dcf3e2; --good-ink:#11602b; --warn-bg:#fff1d6; --warn-ink:#7a4b00;
  --bad-bg:#fde2df; --bad-ink:#a1251b; --flag-bg:#f1f8f3;
  --radius:18px; --shadow:0 1px 2px rgba(20,23,26,.06), 0 4px 14px rgba(20,23,26,.06);
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg:#0f1114; --card:#1a1d21; --ink:#eef1f4; --ink2:#c9d0d8; --muted:#9ba5b2; --line:#2c3138;
    --pepsi:#3b8ee0; --cult:#e06a1f;
    --good-bg:#173d24; --good-ink:#93e3aa; --warn-bg:#3d2e0f; --warn-ink:#ffd27a;
    --bad-bg:#47191a; --bad-ink:#ffaba2; --flag-bg:#16261c;
    --shadow:none;
  }
}
* { box-sizing:border-box; }
html { -webkit-text-size-adjust:100%; }
body { margin:0; background:var(--bg); color:var(--ink);
  font:16px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  padding:calc(12px + env(safe-area-inset-top)) calc(16px + env(safe-area-inset-right))
          calc(24px + env(safe-area-inset-bottom)) calc(16px + env(safe-area-inset-left)); }
main { max-width:680px; margin:0 auto; }
h1 { font-size:1.6rem; line-height:1.15; margin:4px 0 2px; letter-spacing:-.01em; }
h2 { font-size:1.1rem; margin:28px 0 10px; display:flex; align-items:baseline; gap:8px; }
h2 .count { font-size:.85rem; color:var(--muted); font-weight:600; }
h3 { font-size:1rem; margin:0; }
p { margin:0; }
a { color:inherit; }
.top { display:flex; flex-direction:column; gap:8px; margin-bottom:16px; }
.date { color:var(--muted); font-size:.95rem; }
.pill { align-self:flex-start; display:inline-flex; align-items:center; gap:8px; min-height:32px;
  padding:6px 12px; border-radius:999px; font-size:.9rem; font-weight:600; }
.pill::before { content:""; width:8px; height:8px; border-radius:50%; background:currentColor; flex:none; }
.pill.fresh { background:var(--good-bg); color:var(--good-ink); }
.pill.warn { background:var(--warn-bg); color:var(--warn-ink); }
.pill.stale { background:var(--bad-bg); color:var(--bad-ink); }
.card { background:var(--card); border-radius:var(--radius); box-shadow:var(--shadow);
  border:1px solid var(--line); padding:16px; min-width:0; }
.summary p { color:var(--ink2); }
.heroes { display:grid; grid-template-columns:repeat(auto-fit, minmax(260px, 1fr)); gap:12px; }
.hero { border-top:6px solid var(--accent); display:flex; flex-direction:column; gap:6px; }
.pepsi { --accent:var(--pepsi); } .cult { --accent:var(--cult); }
.product { display:inline-flex; align-items:center; gap:6px; font-size:.85rem; font-weight:600; color:var(--ink2); }
.product::before { content:""; width:10px; height:10px; border-radius:50%; background:var(--accent); flex:none; }
.hero .store { font-size:1.15rem; font-weight:700; }
.big { font-size:2.6rem; font-weight:800; line-height:1; letter-spacing:-.02em; font-variant-numeric:tabular-nums; }
.big small { font-size:1rem; font-weight:600; color:var(--muted); letter-spacing:0; margin-left:4px; }
.facts { color:var(--ink2); font-size:.95rem; font-variant-numeric:tabular-nums; }
.until { font-weight:600; }
.empty { color:var(--muted); }
.badge { align-self:flex-start; display:inline-flex; align-items:center; gap:6px; padding:4px 10px;
  border-radius:999px; background:var(--good-bg); color:var(--good-ink); font-size:.85rem; font-weight:700; }
.badge::before { content:"\\2713"; }
.why { color:var(--muted); font-size:.85rem; }
ul.cards, ul.strip, ul.plain { list-style:none; margin:0; padding:0; }
ul.cards { display:flex; flex-direction:column; gap:10px; }
.offer { border-left:5px solid var(--accent); display:flex; flex-direction:column; gap:4px; }
.offer.flagged { background:var(--flag-bg); border-color:var(--line); border-left-color:var(--accent);
  box-shadow:inset 0 0 0 1px var(--good-bg), var(--shadow); }
.row { display:flex; justify-content:space-between; align-items:baseline; gap:12px; }
.offer .store { font-weight:700; font-size:1.05rem; overflow-wrap:anywhere; }
.price { font-size:1.4rem; font-weight:800; white-space:nowrap; font-variant-numeric:tabular-nums; }
.price small { font-size:.8rem; font-weight:600; color:var(--muted); margin-left:2px; }
.meta { color:var(--muted); font-size:.875rem; }
.vs { font-weight:700; color:var(--ink2); }
.note { font-style:italic; color:var(--muted); font-size:.875rem; }
.desc { color:var(--muted); font-size:.8rem; overflow-wrap:anywhere; display:-webkit-box;
  -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
a.go { align-self:flex-start; display:inline-flex; align-items:center; min-height:44px; padding:0 4px;
  font-weight:600; color:var(--accent); text-underline-offset:3px; }
ul.strip { display:flex; gap:10px; overflow-x:auto; scroll-snap-type:x mandatory; padding:2px 2px 10px;
  margin:0 -16px; padding-left:16px; padding-right:16px; scroll-padding-left:16px; -webkit-overflow-scrolling:touch; }
ul.strip > li { flex:0 0 min(78%, 300px); scroll-snap-align:start; }
.charts { display:grid; grid-template-columns:repeat(auto-fit, minmax(280px, 1fr)); gap:12px; }
.chart svg { display:block; width:100%; height:auto; margin-top:8px; }
.chart .sub { color:var(--muted); font-size:.85rem; }
.chart .grid { stroke:var(--line); stroke-width:1; }
.chart .axis { fill:var(--muted); font-size:11px; }
.chart .label { fill:var(--ink); font-size:12px; font-weight:700; }
.chart .line { fill:none; stroke:var(--accent); stroke-width:2; stroke-linejoin:round; stroke-linecap:round; }
.chart .pt { fill:var(--accent); stroke:var(--card); stroke-width:2; }
.placeholder { margin-top:10px; padding:28px 12px; border:2px dashed var(--line); border-radius:12px;
  text-align:center; color:var(--muted); }
.caption { color:var(--muted); font-size:.85rem; margin-top:6px; }
details { margin-top:10px; }
details > summary { min-height:44px; display:flex; align-items:center; cursor:pointer; font-weight:600; list-style:none; }
details > summary::-webkit-details-marker { display:none; }
details > summary::after { content:"+"; margin-left:auto; font-size:1.3rem; color:var(--muted); }
details[open] > summary::after { content:"\\2212"; }
details .inner { padding-top:6px; display:flex; flex-direction:column; gap:10px; }
ul.plain > li { padding:8px 0; border-top:1px solid var(--line); overflow-wrap:anywhere; }
ul.plain > li:first-child { border-top:0; }
.err { color:var(--bad-ink); } .warnline { margin-top:10px; font-weight:600; }
.chart details { margin-top:4px; }
.chart details > summary { font-weight:500; color:var(--muted); font-size:.9rem; }
footer { margin-top:28px; color:var(--muted); font-size:.8rem; text-align:center; }
"""

# Upgrades the pill when the page itself has gone stale: the run date is fixed in the file,
# so a phone opening an old page (the PC was off, a push failed) still sees the warning.
# It adds to the text, so a source-error or stale warning already there stays.
AGE_JS = """
(function () {
  var p = document.getElementById('fresh');
  if (!p) return;
  var days = Math.floor((Date.now() - new Date(p.dataset.run + 'T00:00:00').getTime()) / 86400000);
  if (days > %d) {
    p.className = 'pill stale';
    p.textContent += '; this page is ' + days + ' days old: the weekly run looks overdue';
  }
})();
""" % STALE_DAYS

# Only the inline style and script may load; no other host, font or image.
CSP = ("default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
       "img-src 'self'; manifest-src 'self'")


def _short(iso):
    """'28 Oct' from '2026-10-28'."""
    return "%d %s" % (int(iso[8:10]), MONTHS[int(iso[5:7]) - 1][:3])


def _kr(value):
    return "%.2f" % value


def _link(url, text="See offer"):
    if url and is_web_url(url):
        return '<a class="go" href="%s" rel="noopener noreferrer">%s</a>' % (escape(url), text)
    return ""


def _css_class(product):
    return dict(PRODUCTS).get(product, "pepsi")


def freshness(errors, extras, today):
    """(pill class, text): stale when over 8 days old or never collected, warn for source errors
    alone, else fresh. Stale data with source errors names both."""
    days = age_days(extras, today)
    parts = []
    if days is None:
        parts.append("No successful collection on record")
    elif days > STALE_DAYS:
        parts.append("Stale: the last successful collection is %d days old" % days)
    stale = bool(parts)
    if errors:
        parts.append("Source errors: some prices may be missing")
    if parts:
        return "stale" if stale else "warn", "; ".join(parts)
    # A date, not "today": the page keeps this text however long it stays up.
    return "fresh", "Fresh: collected %s" % _short(extras.last_success)


def _badge(flag):
    if not flag:
        return ""
    why = flag.split(":", 1)[1].strip() if ":" in flag else ""
    return '<span class="badge">Good offer</span>%s' % (
        '<span class="why">%s</span>' % escape(why) if why else "")


def _dates(o):
    if not o.valid_to:
        return "from %s" % _short(o.valid_from)
    if o.valid_from == o.valid_to:
        return "on %s" % _short(o.valid_to)
    return "%s to %s" % (_short(o.valid_from), _short(o.valid_to))


def _hero(product, available):
    cls = _css_class(product)
    rows = [t for t in available if t[0].product == product and t[3] != VARIANTS_NOTE]
    out = ['<section class="card hero hero-%s %s">' % (cls, cls),
           '<span class="product">%s</span>' % escape(product)]
    if not rows:
        out.append('<p class="empty">No %s offer from Danish chains right now.</p></section>' % escape(product))
        return "".join(out)
    low = round(min(t[0].kr_per_l for t in rows), 2)
    best = [t for t in rows if round(t[0].kr_per_l, 2) == low]
    o, vs, _base, _note, flag = best[0]
    others = list(dict.fromkeys(t[0].store for t in best[1:] if t[0].store != o.store))
    out += ['<span class="store">%s</span>' % escape(o.store),
            '<span class="big">%s<small>kr/can</small></span>' % _kr(kr_per_can(o)),
            '<span class="facts">%s kr/L &middot; %s for %s kr%s</span>' % (
                _kr(o.kr_per_l), escape(_pack(o.pack)), _kr(o.price_dkk),
                ' &middot; <span class="vs">%s vs 12-wk avg</span>' % escape(vs) if vs else ""),
            '<span class="until">%s</span>' % (
                "until %s" % _short(o.valid_to) if o.valid_to else "no end date given")]
    if others:
        out.append('<span class="meta">Same price at %s</span>' % escape(", ".join(others)))
    out += [_badge(flag), _link(o.url), "</section>"]
    return "".join(out)


def _offer_card(t, extra_class=""):
    o, vs, _base, note, flag = t
    cls = _css_class(o.product)
    meta = [escape(o.product), _dates(o)]
    if not o.campaign:
        meta.append("shelf price")
    if o.slot:
        meta.append("delivery slot %s" % escape(o.slot))
    return "".join([
        '<li class="card offer %s%s%s">' % (cls, " flagged" if flag else "", extra_class),
        '<div class="row"><span class="store">%s</span><span class="price">%s<small>kr/can</small></span></div>'
        % (escape(o.store), _kr(kr_per_can(o))),
        '<div class="facts">%s &middot; %s kr &middot; %s kr/L%s</div>' % (
            escape(_pack(o.pack)), _kr(o.price_dkk), _kr(o.kr_per_l),
            ' &middot; <span class="vs">%s vs 12-wk avg</span>' % escape(vs) if vs else ""),
        '<div class="meta">%s</div>' % " &middot; ".join(meta),
        '<div class="note">%s</div>' % escape(note) if note else "",
        _badge(flag),
        '<div class="desc">%s</div>' % escape(o.description) if o.description else "",
        _link(o.url),
        "</li>"])


def _coming_card(t):
    o, _vs, _base, note, _flag = t
    cls = _css_class(o.product)
    return "".join([
        '<li class="card offer %s">' % cls,
        '<span class="product">%s</span>' % escape(o.product),
        '<div class="row"><span class="store">%s</span><span class="price">%s<small>kr/can</small></span></div>'
        % (escape(o.store), _kr(kr_per_can(o))),
        '<div class="facts">%s kr/L &middot; %s for %s kr</div>' % (
            _kr(o.kr_per_l), escape(_pack(o.pack)), _kr(o.price_dkk)),
        '<div class="until">from %s%s</div>' % (
            _short(o.valid_from), " to %s" % _short(o.valid_to) if o.valid_to else ""),
        '<div class="note">%s</div>' % escape(note) if note else "",
        _link(o.url),
        "</li>"])


# Chart geometry in SVG user units; the SVG scales to the card width.
W, H = 320, 170
PAD_L, PAD_R, PAD_T, PAD_B = 40, 14, 20, 30


def _chart(product, extras):
    cls = _css_class(product)
    stores = extras.weekly.get(product, {})
    labels = extras.week_labels
    lows = [min((cells[w] for cells in stores.values() if w in cells), default=None) for w in labels]
    points = [(i, v) for i, v in enumerate(lows) if v is not None]
    out = ['<section class="card chart chart-%s %s">' % (cls, cls),
           '<span class="product">%s</span>' % escape(product),
           '<p class="sub">Lowest kr/L per week, last %d weeks</p>' % len(labels)]
    if len(points) < 2:
        out.append('<div class="placeholder">%s<br>Weeks with prices so far: %d.</div></section>'
                   % (CHART_PLACEHOLDER, len(points)))
        return "".join(out)
    current = labels[-1]
    # This week's store prices go in the caption, not the plot: one dear store would
    # stretch the scale and flatten the line that matters.
    dots = sorted((cells[current], store) for store, cells in stores.items() if current in cells)
    values = [v for _, v in points]
    lo, hi = min(values), max(values)
    pad = max(hi - lo, 0.5) * 0.15
    y_lo, y_hi = lo - pad, hi + pad

    def x(i):
        return PAD_L + i * (W - PAD_L - PAD_R) / max(len(labels) - 1, 1)

    def y(v):
        return PAD_T + (y_hi - v) / (y_hi - y_lo) * (H - PAD_T - PAD_B)

    svg = ['<svg viewBox="0 0 %d %d" role="img" aria-label="%s">' % (W, H, escape(
        "%s lowest kr/L per week: %s" % (product, ", ".join(
            "%s %s" % (labels[i], _kr(v)) for i, v in points)))) ]
    for v in sorted({lo, hi}):
        svg.append('<line class="grid" x1="%d" x2="%d" y1="%.1f" y2="%.1f"/>' % (PAD_L, W - PAD_R, y(v), y(v)))
        svg.append('<text class="axis" x="%d" y="%.1f" text-anchor="end" dominant-baseline="middle">%s</text>'
                   % (PAD_L - 6, y(v), _kr(v)))
    svg.append('<text class="axis" x="%d" y="%d" text-anchor="start">%s</text>' % (PAD_L, H - 6, escape(labels[0])))
    svg.append('<text class="axis" x="%d" y="%d" text-anchor="end">%s</text>' % (W - PAD_R, H - 6, escape(current)))
    path, prev = [], None
    for i, v in points:
        path.append("%s%.1f %.1f" % ("L" if prev is not None and i == prev + 1 else "M", x(i), y(v)))
        prev = i
    svg.append('<path class="line" d="%s"/>' % " ".join(path))
    for i, v in points:
        svg.append('<circle class="pt" cx="%.1f" cy="%.1f" r="4.5"><title>%s: %s kr/L</title></circle>'
                   % (x(i), y(v), escape(labels[i]), _kr(v)))
    last_i, last_v = points[-1]
    # The label sits on the side the line does not come from, so the two never cross.
    below = points[-2][1] > last_v
    svg.append('<text class="label" x="%.1f" y="%.1f" text-anchor="end">%s</text>'
               % (x(last_i) - 8, y(last_v) + (18 if below else -9), _kr(last_v)))
    low_i, low_v = min(points, key=lambda p: (p[1], -p[0]))
    if low_i != last_i:
        svg.append('<text class="label" x="%.1f" y="%.1f" text-anchor="middle">low %s</text>'
                   % (x(low_i), min(y(low_v) + 18, H - PAD_B + 4), _kr(low_v)))
    svg.append("</svg>")
    out += svg
    if dots:
        out.append('<p class="caption">This week: %s</p>' % escape(", ".join(
            "%s %s" % (store, _kr(kr)) for kr, store in dots)))
    out.append('<details><summary>Show the numbers</summary><ul class="plain">%s</ul></details>' % "".join(
        "<li>%s: %s kr/L</li>" % (escape(labels[i]), _kr(v)) for i, v in reversed(points)))
    out.append("</section>")
    return "".join(out)


def _details(errors, quarantined, coverage):
    out = ['<section class="card more">']
    if errors:
        out.append('<details open><summary>Source errors (%d)</summary><div class="inner">'
                   '<ul class="plain err">%s</ul><p class="meta">Offers from a failed source are missing.</p>'
                   '</div></details>' % (len(errors), "".join(
                       "<li>%s: %s</li>" % (escape(s), escape(m)) for s, m in errors)))
    else:
        out.append('<details><summary>Source errors (0)</summary><div class="inner">'
                   '<p class="meta">Every source answered.</p></div></details>')
    items = []
    for q in quarantined:
        price = "" if q.price_dkk is None else " &middot; %s kr" % _kr(q.price_dkk)
        items.append("<li><strong>%s</strong> &middot; %s%s<br><span class=\"meta\">%s</span><br>"
                     "<span class=\"note\">%s</span>%s</li>" % (
                         escape(q.store), escape(q.product or "unknown"), price, escape(q.description),
                         escape(q.reason), _link(q.url)))
    out.append('<details><summary>Quarantined rows (%d)</summary><div class="inner">'
               '<p class="meta">Rows that look relevant but could not be read safely. '
               'They are kept out of the price history.</p>%s</div></details>' % (
                   len(quarantined), '<ul class="plain">%s</ul>' % "".join(items) if items else ""))
    seen = sum(1 for c in coverage if c["seen"])
    out.append('<details><summary>Coverage: %d of %d chains seen</summary><div class="inner">'
               '<ul class="plain">%s</ul></div></details>' % (seen, len(coverage), "".join(
                   "<li><strong>%s</strong> &middot; %s</li>" % (escape(c["chain"]), (
                       "%d kept, %d variants, %d quarantined, %d bottles dropped" % (
                           c["accepted"], c["variants"], c["quarantined"], c["bottles"])
                       if c["seen"] else NOT_SEEN)) for c in coverage)))
    out.append("</section>")
    return out


def page_html(run_id, listed, quarantined, errors, today, extras):
    """The whole page as one string."""
    available, later = split_listed(listed, today)
    pill, pill_text = freshness(errors, extras, today)
    ages = age_lines(extras, today)
    out = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">',
           '<meta http-equiv="Content-Security-Policy" content="%s">' % CSP,
           '<meta name="theme-color" content="#0060c7" media="(prefers-color-scheme: light)">',
           '<meta name="theme-color" content="#0f1114" media="(prefers-color-scheme: dark)">',
           '<meta name="apple-mobile-web-app-capable" content="yes">',
           '<meta name="mobile-web-app-capable" content="yes">',
           '<meta name="apple-mobile-web-app-title" content="Pepsi &amp; Cult">',
           '<meta name="referrer" content="no-referrer">',
           '<link rel="icon" href="icon.svg" type="image/svg+xml">',
           '<link rel="apple-touch-icon" href="icon.svg">',
           '<link rel="manifest" href="manifest.webmanifest">',
           "<title>%s</title><style>%s</style></head><body><main>" % (escape(TITLE), STYLE),
           '<header class="top"><h1>%s</h1>' % escape(TITLE),
           '<p class="date">Prices for %s %s</p>' % (_short(today.isoformat()), today.year),
           '<span class="pill %s" id="fresh" data-run="%s">%s</span>' % (pill, today.isoformat(), escape(pill_text)),
           "</header>",
           '<section class="card summary"><p>%s</p></section>' % escape(summary_for(listed, errors, today, extras))]
    if len(ages) > 1:
        out.append('<p class="err warnline">%s</p>' % escape(ages[-1]))
    out.append("<h2>Best right now</h2>")
    out.append('<div class="heroes">%s</div>' % "".join(_hero(p, available) for p, _ in PRODUCTS))
    out.append('<h2>Available now <span class="count">%d</span></h2>' % len(available))
    out.append('<section class="available offers">%s</section>' % (
        '<ul class="cards">%s</ul>' % "".join(_offer_card(t) for t in available) if available
        else '<p class="empty">No offers right now.</p>'))
    out.append('<h2>Coming up <span class="count">%d</span></h2>' % len(later))
    out.append('<section class="coming">%s</section>' % (
        '<ul class="strip">%s</ul>' % "".join(_coming_card(t) for t in later) if later
        else '<p class="empty">Nothing announced yet.</p>'))
    out.append("<h2>Price over time</h2>")
    out.append('<div class="charts">%s</div>' % "".join(_chart(p, extras) for p, _ in PRODUCTS))
    out.append("<h2>Details</h2>")
    out += _details(errors, quarantined, extras.coverage)
    out.append('<footer>Cans only. Prices exclude pant; kr/L and kr/can are worked out from them. '
               '%s.<br>Run %s.</footer>' % (escape(ages[0]), escape(run_id)))
    out.append("</main><script>%s</script></body></html>" % AGE_JS)
    return "\n".join(out) + "\n"


def write_mobile(out_dir, run_id, listed, quarantined, errors, today, extras):
    """Write index.html plus the manifest, icon and .nojekyll into out_dir; returns the page path."""
    os.makedirs(out_dir, exist_ok=True)
    for name, text in STATIC_FILES.items():
        with open(os.path.join(out_dir, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    path = os.path.join(out_dir, PAGE)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(page_html(run_id, listed, quarantined, errors, today, extras))
    return path
