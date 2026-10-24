"""The phone page docs/index.html and its manifest, icon and .nojekyll."""
import contextlib
import csv
import io
import json
import os
import re
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import date

from dealfinder.cli import main
from dealfinder.history import Baseline, Observation
from dealfinder.match import VARIANTS_NOTE
from dealfinder.mobile import (CHART_PLACEHOLDER, PAGE, STATIC_FILES, page_html, write_mobile)
from dealfinder.report import Extras

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "tests", "fixtures", "sample")
TODAY = date(2026, 10, 24)
GOOD = "good offer: under 10 kr/L"
LABELS = ["W%02d" % n for n in range(32, 44)]


def row(store, price, product="Pepsi Max", pack="24 x 0.33 L cans", frm="2026-10-22", to="2026-10-28",
        note="", flag="", base=None, vs="", url="https://example.dk/offer", description="d"):
    liters = 7.92 if pack.startswith("24") else 0.33
    o = Observation(run_id="r", run_date="2026-10-24", product=product, source="tjek", source_id=store,
                    product_id="", store=store, description=description, pack=pack, volume_l=liters,
                    price_dkk=price, kr_per_l=round(price / liters, 2), valid_from=frm, valid_to=to,
                    campaign=True, url=url)
    return o, vs, base, note, flag


def extras(weekly=None, last_success="2026-10-24"):
    return Extras(coverage=[{"chain": "Netto", "accepted": 1, "variants": 0, "quarantined": 0,
                             "bottles": 0, "seen": True},
                            {"chain": "Lidl", "accepted": 0, "variants": 0, "quarantined": 0,
                             "bottles": 0, "seen": False}],
                  weekly=weekly or {}, week_labels=LABELS, last_success=last_success)


def page(listed=(), errors=(), quarantined=(), **kw):
    return page_html("2026-10-24T06:00:00Z", list(listed), list(quarantined), list(errors), TODAY,
                     extras(**kw))


def section(html, cls):
    """The text of the first <section> whose class list holds cls."""
    m = re.search(r'<section class="[^"]*\b%s\b[^"]*".*?</section>' % re.escape(cls), html, re.S)
    return m.group(0) if m else ""


URL_ATTR = re.compile(r"""\b(?:src|href|action|poster|data)\s*=\s*["']?([^"'\s>]+)""", re.I)


def external_refs(html, allowed):
    """Every src/href-like value that leaves the page, other than the allowed offer links."""
    out = [u for u in URL_ATTR.findall(html)
           if re.match(r"(?:[a-z][a-z0-9+.-]*:)?//", u, re.I) and u not in allowed]
    out += re.findall(r"url\(|@import", html)
    return out


class PageTest(unittest.TestCase):
    def test_head_tags_for_a_home_screen_app(self):
        html = page([row("Netto", 75)])
        for tag in ('<meta name="viewport" content="width=device-width, initial-scale=1',
                    '<meta name="theme-color"', '<meta name="apple-mobile-web-app-capable" content="yes">',
                    '<link rel="apple-touch-icon" href="icon.svg">',
                    '<link rel="manifest" href="manifest.webmanifest">',
                    "<title>Pepsi Max &amp; Cult</title>"):
            self.assertIn(tag, html)
        self.assertIn("prefers-color-scheme: dark", html)

    def test_no_external_requests_only_offer_links_leave_the_page(self):
        listed = [row("Netto", 75, url="https://netto.dk/a"), row("Bilka", 80, url="http://bilka.dk/b"),
                  row("Later", 70, frm="2026-10-29", to="2026-11-02", url="https://later.dk/c")]
        q = [_Quarantined("føtex", "https://foetex.dk/q")]
        html = page(listed, quarantined=q,
                    weekly={"Pepsi Max": {"Netto": {"W42": 9.6, "W43": 9.47}}})
        allowed = {"https://netto.dk/a", "http://bilka.dk/b", "https://later.dk/c", "https://foetex.dk/q"}
        self.assertEqual(external_refs(html, allowed), [])
        for url in allowed:
            self.assertIn('href="%s"' % url, html)
        self.assertNotIn("xmlns", html)

    def test_scraped_text_is_escaped_and_only_http_links_are_links(self):
        listed = [row("<b>Netto</b>", 75, description="<script>alert(1)</script> & co",
                      url="javascript:alert(1)")]
        html = page(listed, errors=[("tjek", "<img src=x onerror=alert(1)>")])
        self.assertNotIn("<script>alert", html)
        self.assertNotIn("<b>Netto</b>", html)
        self.assertNotIn("<img src=x", html)
        self.assertIn("&lt;b&gt;Netto&lt;/b&gt;", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt; &amp; co", html)
        self.assertNotIn('href="javascript:', html)

    def test_chart_placeholder_under_two_weeks(self):
        html = page([row("Netto", 75)], weekly={"Pepsi Max": {"Netto": {"W43": 9.47}}})
        chart = section(html, "chart-pepsi")
        self.assertIn(CHART_PLACEHOLDER, chart)
        self.assertNotIn("<svg", chart)
        self.assertIn(CHART_PLACEHOLDER, section(page(), "chart-pepsi"))

    def test_chart_is_an_svg_with_two_or_more_weeks(self):
        weekly = {"Pepsi Max": {"Netto": {"W40": 10.2, "W41": 9.9, "W43": 9.47},
                                "Bilka": {"W41": 9.6, "W43": 9.8}}}
        chart = section(page([row("Netto", 75)], weekly=weekly), "chart-pepsi")
        self.assertIn("<svg", chart)
        self.assertNotIn(CHART_PLACEHOLDER, chart)
        # One point per week with data, at that week's lowest store price.
        self.assertEqual(re.findall(r"<title>(W\d\d): ([\d.]+) kr/L</title>", chart),
                         [("W40", "10.20"), ("W41", "9.60"), ("W43", "9.47")])
        # W42 has no price, so the line breaks there instead of drawing through it.
        path = re.search(r'<path class="line" d="([^"]+)"', chart).group(1)
        self.assertEqual(path.count("M"), 2)
        self.assertIn("This week: Netto 9.47, Bilka 9.80", chart)
        self.assertIn(CHART_PLACEHOLDER, section(page(weekly=weekly), "chart-cult"))

    def test_freshness_pill(self):
        fresh = page([row("Netto", 75)])
        self.assertIn('class="pill fresh"', fresh)
        stale = page([row("Netto", 75)], last_success="2026-10-14")
        self.assertIn('class="pill stale"', stale)
        self.assertIn("10 days old", stale)
        errors = page([row("Netto", 75)], errors=[("rema", "HTTP 500")], last_success="2026-10-20")
        self.assertIn('class="pill warn"', errors)
        self.assertIn("Source errors", errors)
        never = page(errors=[("rema", "HTTP 500")], last_success="")
        self.assertIn('class="pill stale"', never)
        self.assertIn("Fresh: collected 24 Oct", fresh)

    def pill(self, html):
        return re.search(r'<span class="(pill [a-z]+)" id="fresh"[^>]*>([^<]*)</span>', html).groups()

    def test_stale_data_with_source_errors_keeps_both_warnings(self):
        cls, text = self.pill(page([row("Netto", 75)], errors=[("rema", "HTTP 500")],
                                   last_success="2026-10-14"))
        self.assertEqual(cls, "pill stale")
        self.assertEqual(text, "Stale: the last successful collection is 10 days old; "
                               "Source errors: some prices may be missing")

    def test_never_collected_with_source_errors_keeps_both_warnings(self):
        cls, text = self.pill(page(errors=[("rema", "HTTP 500")], last_success=""))
        self.assertEqual(cls, "pill stale")
        self.assertEqual(text, "No successful collection on record; Source errors: some prices may be missing")

    def test_page_age_script_adds_to_the_pill_text(self):
        html = page([row("Netto", 75)], errors=[("rema", "HTTP 500")])
        script = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
        self.assertIn("p.textContent += ", script)
        self.assertNotRegex(script, r"textContent\s*=[^=]")
        self.assertIn("days > 8", script)

    def test_best_right_now_skips_variants_and_shows_end_date_and_badge(self):
        listed = [row("SPAR", 52.27, note=VARIANTS_NOTE),
                  row("Netto", 75, flag=GOOD, to="2026-10-28"),
                  row("Bilka", 80)]
        hero = section(page(listed), "hero-pepsi")
        self.assertIn("Netto", hero)
        self.assertNotIn("SPAR", hero)
        self.assertIn("3.13", hero)  # kr/can
        self.assertIn("9.47 kr/L", hero)
        self.assertIn("until 28 Oct", hero)
        self.assertIn("Good offer", hero)
        self.assertIn("No Cult Energy offer", section(page(listed), "hero-cult"))

    def test_available_cards_sorted_by_kr_per_l_with_percent_and_flag_accent(self):
        base = Baseline(10.5, 9.0, 12, 5)
        listed = [row("Dyr", 90, vs="+8%", base=base), row("Billig", 75, flag=GOOD, vs="-10%", base=base),
                  row("Mellem", 80, vs="-4%", base=base)]
        avail = section(page(listed), "available")
        stores = re.findall(r'<span class="store">([^<]+)</span>', avail)
        self.assertEqual(stores, ["Billig", "Mellem", "Dyr"])
        self.assertIn("-10% vs 12-wk avg", avail)
        self.assertEqual(avail.count("flagged"), 1)
        self.assertNotIn("vs 12-wk avg", section(page([row("Netto", 75)]), "available"))

    def test_coming_up_strip_holds_the_later_rows(self):
        listed = [row("Netto", 75), row("nemlig.com", 82, frm="2026-10-29", to="2026-11-04")]
        upcoming = section(page(listed), "coming")
        self.assertIn("nemlig.com", upcoming)
        self.assertIn("from 29 Oct", upcoming)
        self.assertNotIn("nemlig.com", section(page(listed), "available"))

    def test_details_for_coverage_quarantine_and_errors(self):
        html = page([row("Netto", 75)], errors=[("rema", "HTTP 500")],
                    quarantined=[_Quarantined("føtex", "")])
        self.assertIn("<details open><summary>Source errors (1)", html)
        self.assertIn("<summary>Quarantined rows (1)", html)
        self.assertIn("<summary>Coverage: 1 of 2 chains seen", html)
        self.assertIn("Lidl", html)


class _Quarantined:
    def __init__(self, store, url):
        self.product, self.store, self.url = "Pepsi Max", store, url
        self.description, self.reason = "Pepsi Max 6-12 stk", "pack size range"
        self.price_dkk, self.valid_from, self.valid_to = 50.0, "2026-10-22", "2026-10-28"


class FilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_writes_the_page_manifest_icon_and_nojekyll(self):
        d = os.path.join(self.tmp, "docs")
        path = write_mobile(d, "run", [row("Netto", 75)], [], [], TODAY, extras())
        self.assertEqual(path, os.path.join(d, PAGE))
        self.assertEqual(sorted(os.listdir(d)), sorted([PAGE, *STATIC_FILES]))
        with open(os.path.join(d, "manifest.webmanifest"), encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["icons"][0]["src"], "icon.svg")
        self.assertEqual(ET.parse(os.path.join(d, "icon.svg")).getroot().tag,
                         "{http://www.w3.org/2000/svg}svg")
        self.assertEqual(os.path.getsize(os.path.join(d, ".nojekyll")), 0)

    def run_cli(self, *extra):
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            code = main(["--offline", FIXTURES, "--history", os.path.join(self.tmp, "h.csv"),
                         "--out", os.path.join(self.tmp, "out"), "--today", "2026-10-24", *extra])
        return code, buf.getvalue()

    def test_offline_run_writes_the_page_to_mobile_dir(self):
        d = os.path.join(self.tmp, "docs")
        code, out = self.run_cli("--mobile-dir", d)
        self.assertEqual(code, 0, out)
        self.assertIn("Phone page: %s" % os.path.join(d, PAGE), out)
        with open(os.path.join(d, PAGE), encoding="utf-8") as f:
            html = f.read()
        self.assertIn("365discount", html)
        with open(os.path.join(self.tmp, "out", "report.csv"), encoding="utf-8", newline="") as f:
            offer_links = {r["url"] for r in csv.DictReader(f)}
        self.assertEqual(external_refs(html, offer_links), [])

    def test_offline_run_leaves_the_committed_docs_alone(self):
        docs = os.path.join(ROOT, "docs")

        def snapshot():
            out = {}
            for name in (PAGE, *STATIC_FILES):
                p = os.path.join(docs, name)
                if os.path.exists(p):
                    with open(p, "rb") as f:
                        out[name] = (f.read(), os.stat(p).st_mtime_ns)
            return out

        before = snapshot()
        code, out = self.run_cli()
        self.assertEqual(code, 0, out)
        self.assertEqual(snapshot(), before)
        self.assertNotIn("Phone page:", out)


if __name__ == "__main__":
    unittest.main()
