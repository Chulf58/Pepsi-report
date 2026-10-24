import contextlib
import csv
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date

from dealfinder.cli import main
from dealfinder.history import HEADER, load_history

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "sample")


def tjek(oid, heading, description, price, store="Netto", run_till="2026-10-29T22:59:59+0000",
         webshop=None):
    return {"id": oid, "heading": heading, "description": description,
            "pricing": {"price": price, "currency": "DKK"},
            "quantity": {"unit": None, "size": {"from": 1, "to": 1},
                         "pieces": {"from": 1, "to": 1}},
            "run_from": "2026-10-22T22:00:00+0000", "run_till": run_till,
            "links": {"webshop": webshop},
            "dealer": {"name": store, "country": {"id": "DK"}, "website": "https://netto.dk"}}


def rema(pid, name, underline, price, deposit, compare, ending="2026-10-31T00:00:00+00:00",
         starting="2026-10-22T00:00:00+00:00"):
    entry = {"price": price, "is_campaign": True, "starting_at": starting,
             "ending_at": ending, "deposit": deposit, "compare_unit": "ltr",
             "compare_unit_price": compare}
    if ending is None:
        del entry["ending_at"]
    return {"id": pid, "name": name, "underline": underline, "description": None,
            "prices": [entry]}


SYNTHETIC_TJEK = [
    tjek("a", "Pepsi Max", "24 x 33 cl. ds. + pant. Literpris 9,47", 75.0),
    tjek("b", "Pepsi Max", "6 x 33 cl ds", 15.84, store="føtex"),
    tjek("v", "Pepsi eller Faxe Kondi", "Flere varianter. 24 x 33 cl ds", 52.27, store="SPAR"),
    tjek("bottle", "Pepsi Max", "1,5 liter. + pant", 12.0),
    tjek("cult", "Cult Energy", "Flere varianter 12 x 0,5 l ds", 69.99, store="Bilka"),
]


class OfflineRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.history = os.path.join(self.tmp, "history.csv")
        self.out = os.path.join(self.tmp, "out")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def fixture(self, tjek_rows, rema_products=(), pepsi_rows=()):
        d = os.path.join(self.tmp, "fx")
        os.makedirs(d, exist_ok=True)
        for name, rows in (("tjek_pepsi_max.json", tjek_rows), ("tjek_cult.json", []),
                           ("tjek_pepsi.json", pepsi_rows)):
            with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                json.dump(rows, f)
        with open(os.path.join(d, "rema_page_1.json"), "w", encoding="utf-8") as f:
            json.dump({"data": list(rema_products), "meta": {"pagination": {"last_page": 1}}}, f)
        # No confirmed ids and no nemlig products, so only the text rules apply.
        with open(os.path.join(d, "products.json"), "w", encoding="utf-8") as f:
            json.dump({}, f)
        return d

    def with_limits(self, fx):
        with open(os.path.join(fx, "products.json"), "w", encoding="utf-8") as f:
            json.dump({"good_offer": {"max_kr_per_l": {"Pepsi Max": 10, "Cult Energy": 12},
                                      "below_average_percent": 10}}, f)
        return fx

    def run_cli(self, today, fixtures=FIXTURES, report_md=None, last_success=None):
        buf = io.StringIO()
        products = os.path.join(fixtures, "products.json")
        extra = ["--products", products] if os.path.exists(products) else []
        if report_md:
            extra += ["--report-md", report_md]
        if last_success:
            extra += ["--last-success", last_success]
        with redirect_stdout(buf):
            code = main(["--offline", fixtures, "--history", self.history,
                         "--out", self.out, "--today", today] + extra)
        return code, buf.getvalue()

    def report_html(self):
        with open(os.path.join(self.out, "report.html"), encoding="utf-8") as f:
            return f.read()

    def report_rows(self):
        with open(os.path.join(self.out, "report.csv"), encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))

    def vs(self):
        return {r["store"]: r["vs_12w_avg"] for r in self.report_rows() if r["status"] == "offer"}

    def seed(self, weekly):
        with open(self.history, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=HEADER)
            w.writeheader()
            for i, (run_date, kr) in enumerate(weekly):
                w.writerow({"run_id": run_date + "T06:00:00Z", "run_date": run_date,
                            "product": "Pepsi Max", "source": "seed", "source_id": str(i), "store": "SeedStore",
                            "kr_per_l": kr})

    def test_real_fixture_run(self):
        code, summary = self.run_cli("2026-10-23")
        self.assertEqual(code, 0, summary)
        rows = load_history(self.history)
        # Cans only; under 1 L without a bottle word counts as a can.
        self.assertEqual(sorted((r["store"], r["pack"], r["kr_per_l"]) for r in rows), [
            ("365discount", "24 x 0.33 L cans", "9.47"),
            ("Bilka", "24 x 0.33 L cans", "9.47"),
            ("Løvbjerg", "24 x 0.33 L cans", "10.1"),
            ("REMA 1000", "0.33 L can", "10.61"),
            ("REMA 1000", "0.33 L can", "20.88"),
            ("REMA 1000", "6 x 0.33 L cans", "20.83"),
            ("nemlig.com", "24 x 0.33 L cans", "15.62"),
            ("nemlig.com", "6 x 0.33 L cans", "20.83"),
            ("nemlig.com", "6 x 0.33 L cans, 2 for 80.00", "20.2"),
        ])
        self.assertIn("Offers kept: Pepsi Max: 9, Cult Energy: 0", summary)
        self.assertIn("Out of stock skipped (nemlig): 1", summary)  # 5061661
        self.assertIn("Requests: nemlig 8, rema 2, tjek 9", summary)
        # Every stored row carries its source product id.
        self.assertTrue(all(r["product_id"] for r in rows))
        campaign = [r for r in rows if r["source_id"] == "5007899@campaign:2026-10-19"][0]
        self.assertEqual((campaign["price_dkk"], campaign["valid_from"], campaign["valid_to"]),
                         ("40.0", "2026-10-19", "2026-10-25"))
        # REMA ids on the confirmed list are not reported as text matches; Tjek rows are.
        self.assertIn("Matched by text, not by a confirmed id: 4", summary)
        self.assertIn("Matched by text", self.report_html())
        self.assertIn("Bottles dropped: 9", summary)
        self.assertIn("BorderShop 2", summary)
        report = self.report_rows()
        quarantined = {(r["store"], r["reason"]) for r in report if r["status"] == "quarantine"}
        # Bilka's mixed flyer row is recovered: 75 kr for the 24 x 33 cl directly before
        # "Pepsi Max" is 9.47 kr/L. Løvbjerg's "/6/20 ds" row stays quarantined.
        self.assertNotIn("Bilka", {store for store, _ in quarantined})
        self.assertIn(("Løvbjerg", "alternative pack counts in text (/6/20 ds)"), quarantined)
        self.assertEqual(len([r for r in report if r["status"] == "quarantine"]), 1)
        stores = {r["store"] for r in report}
        self.assertFalse(stores & {"Netto", "SuperBrugsen", "Kvickly", "MENY", "BorderShop"})
        # No % before 4 weeks of history; the cell stays blank.
        self.assertEqual({r["vs_12w_avg"] for r in report if r["status"] == "offer"}, {""})
        self.assertIn("Pepsi Max not enough history yet", summary)
        # Each section is sorted by kr/L; REMA's 10.61 offer starts after the run date.
        for section in ("available", "later"):
            kr = [float(r["kr_per_l"]) for r in report
                  if r["status"] == "offer" and r["section"] == section]
            self.assertEqual(kr, sorted(kr))
        self.assertEqual([(r["store"], r["kr_per_l"], r["valid_from"]) for r in report
                          if r["section"] == "later"],
                         [("nemlig.com", "10.35", "2026-10-31"),
                          ("REMA 1000", "10.61", "2026-10-29"),
                          ("nemlig.com", "12.37", "2026-10-31"),
                          ("nemlig.com", "20.2", "2026-10-31")])
        html = self.report_html()
        self.assertIn("Quarantine", html)
        self.assertNotIn('<h2 class="err">Source errors', html)

    def test_variants_listed_but_not_stored_and_bottles_dropped(self):
        code, summary = self.run_cli("2026-10-23", self.fixture(SYNTHETIC_TJEK))
        self.assertEqual(code, 0, summary)
        offers = {r["store"]: r for r in self.report_rows() if r["status"] == "offer"}
        self.assertEqual(set(offers), {"Netto", "føtex", "SPAR", "Bilka"})
        self.assertEqual(offers["SPAR"]["note"], "variants, Max likely")
        self.assertEqual(offers["SPAR"]["kr_per_l"], "6.6")
        self.assertEqual(offers["Bilka"]["product"], "Cult Energy")
        # run_from 2026-10-22T22:00:00+0000 is midnight on the 23rd in Copenhagen.
        self.assertEqual(offers["Netto"]["valid_from"], "2026-10-23")
        self.assertIn("variants, Max likely", self.report_html())
        stored = {r["source_id"] for r in load_history(self.history)}
        self.assertEqual(stored, {"a", "b", "cult"})
        self.assertIn("Listed as 'variants, Max likely' (not in history): 1", summary)
        self.assertIn("Bottles dropped: 1", summary)
        # Same offers from three search centres are kept once.
        self.assertEqual(len(load_history(self.history)), 3)

    def test_percent_vs_12_week_average(self):
        # Four prior weeks, mean 10.0 kr/L, low 9.0.
        self.seed([("2026-09-28", "9"), ("2026-10-05", "10"), ("2026-10-12", "11"),
                   ("2026-10-19", "10")])
        code, summary = self.run_cli("2026-10-23", self.fixture(SYNTHETIC_TJEK))
        self.assertEqual(code, 0, summary)
        vs = self.vs()
        self.assertEqual(vs["Netto"], "-5%")  # 9.47
        self.assertEqual(vs["føtex"], "-20%")  # 8.0
        self.assertEqual(vs["SPAR"], "")  # variants row: listed, no %
        self.assertEqual(vs["Bilka"], "")  # Cult has no history
        offers = [r for r in self.report_rows() if r["status"] == "offer"]
        self.assertEqual([r["store"] for r in offers], ["SPAR", "føtex", "Netto", "Bilka"])
        netto = [r for r in offers if r["store"] == "Netto"][0]
        self.assertEqual((netto["avg_12w"], netto["low_12w"]), ("10.0", "9.0"))
        html = self.report_html()
        self.assertIn("-20%", html)
        self.assertIn("12-wk low", html)
        self.assertNotIn("Top deal", html)
        self.assertIn("Pepsi Max 10.00 kr/L (low 9.00, 4 offers, 4 weeks)", summary)

    def test_current_run_left_out_of_its_own_average(self):
        fx = self.fixture(SYNTHETIC_TJEK)
        self.seed([("2026-09-28", "8.5"), ("2026-10-05", "10"), ("2026-10-12", "11")])
        self.run_cli("2026-10-23", fx)
        # Three prior weeks only; this run's own offers do not count.
        self.assertEqual(set(self.vs().values()), {""})
        # A second run sees the first: Pepsi Max offers 8.5, 10, 11, 9.47, 8.0 -> mean 9.39.
        self.run_cli("2026-10-23", fx)
        vs = self.vs()
        self.assertEqual((vs["Netto"], vs["føtex"]), ("+1%", "-15%"))
        with open(self.history, encoding="utf-8") as f:
            self.assertEqual(f.readline().strip(), ",".join(HEADER))

    def test_bad_rows_reported_and_run_continues(self):
        rows = SYNTHETIC_TJEK[:1] + [
            tjek("late", "Pepsi Max", "6 x 33 cl ds", 15.0, run_till="next week"),
            {k: v for k, v in tjek("x", "Pepsi Max", "6 x 33 cl ds", 15.0).items() if k != "id"},
        ]
        products = [rema(211240, "PEPSI MAX", "33 CL. DÅSE", 6.89, 1, 20.88, ending=None),
                    rema(211241, "PEPSI MAX", "33 CL. DÅSE", 6.89, 1, 20.88)]
        code, summary = self.run_cli("2026-10-23", self.fixture(rows, products))
        self.assertEqual(code, 2, summary)
        html = self.report_html()
        self.assertIn('<h2 class="err">Source errors', html)
        self.assertIn("offer late skipped", html)
        self.assertIn("offer None skipped: missing offer id", html)
        self.assertIn("product 211240 price skipped: missing timestamp", html)
        stored = {r["source_id"] for r in load_history(self.history)}
        self.assertEqual(stored, {"a", "211241@2026-10-22"})

    def test_confirmed_id_beats_text_rules(self):
        rows = [tjek("conf", "Pepsi Max Xtreme Edition", "6 x 33 cl ds", 15.84)]
        fx = self.fixture(rows)
        with open(os.path.join(fx, "products.json"), "w", encoding="utf-8") as f:
            json.dump({"tjek": {"Pepsi Max": ["conf"]}}, f)
        code, summary = self.run_cli("2026-10-23", fx)
        self.assertEqual(code, 0, summary)
        self.assertEqual([r["product_id"] for r in load_history(self.history)], ["conf"])
        self.assertIn("Matched by text, not by a confirmed id: 0", summary)

    def test_unknown_id_falls_back_to_text_rules(self):
        rows = [tjek("unk", "Pepsi Max Xtreme Edition", "6 x 33 cl ds", 15.84),
                tjek("txt", "Pepsi Max", "6 x 33 cl ds", 15.84)]
        code, summary = self.run_cli("2026-10-23", self.fixture(rows))
        self.assertEqual([r["product_id"] for r in load_history(self.history)], ["txt"])
        q = [r for r in self.report_rows() if r["status"] == "quarantine"]
        self.assertEqual(q[0]["reason"], "unexplained words after 'Pepsi Max'")
        self.assertIn("Matched by text, not by a confirmed id: 1", summary)
        self.assertIn("<td>txt</td>", self.report_html())

    def test_confirmed_id_still_needs_a_can(self):
        rows = [tjek("conf", "Pepsi Max", "1,5 liter", 12.0)]
        fx = self.fixture(rows)
        with open(os.path.join(fx, "products.json"), "w", encoding="utf-8") as f:
            json.dump({"tjek": {"Pepsi Max": ["conf"]}}, f)
        code, summary = self.run_cli("2026-10-23", fx)
        self.assertEqual(load_history(self.history), [])
        self.assertIn("Bottles dropped: 1", summary)

    def test_history_with_old_columns_is_refused(self):
        with open(self.history, "w", encoding="utf-8") as f:
            f.write("run_id,run_date,product\n")
        with self.assertRaises(ValueError):
            self.run_cli("2026-10-23", self.fixture(SYNTHETIC_TJEK))

    def test_non_http_link_is_not_a_link(self):
        rows = [tjek("j", "Pepsi Max", "6 x 33 cl ds", 15.0, webshop="javascript:alert(1)")]
        self.run_cli("2026-10-23", self.fixture(rows))
        html = self.report_html()
        self.assertNotIn('href="javascript', html)
        self.assertIn("javascript:alert(1)", html)

    def test_csv_formula_cells_are_quoted(self):
        rows = [tjek("f", "=HYPERLINK(1) Pepsi Max", "6 x 33 cl ds", 15.0, store="Netto")]
        self.run_cli("2026-10-23", self.fixture(rows))
        offer = [r for r in self.report_rows() if r["status"] == "offer"][0]
        self.assertTrue(offer["description"].startswith("'=HYPERLINK"), offer["description"])

    def test_source_error_is_reported_and_sets_exit_status(self):
        partial = os.path.join(self.tmp, "partial")
        os.mkdir(partial)
        for name in ("tjek_pepsi_max.json", "tjek_cult.json", "tjek_pepsi.json"):
            shutil.copy(os.path.join(FIXTURES, name), partial)
        code, summary = self.run_cli("2026-10-23", fixtures=partial)
        self.assertEqual(code, 2)
        self.assertIn("REMA", summary)
        html = self.report_html()
        self.assertIn('<h2 class="err">Source errors', html)
        self.assertIn("rema_page_1.json", html)
        # Tjek observations are still recorded.
        self.assertTrue(load_history(self.history))

    def test_nemlig_slot_and_next_week_prices(self):
        code, summary = self.run_cli("2026-10-24")
        self.assertEqual(code, 0, summary)
        nemlig = [r for r in self.report_rows() if r["store"] == "nemlig.com"]
        self.assertTrue(all(r["delivery_slot"] == "2026102414-60-240, zone 1" or
                            r["note"] == "next week, nemlig slot" for r in nemlig))
        self.assertIn("2026102414-60-240, zone 1", {r["delivery_slot"] for r in nemlig})
        later = [r for r in nemlig if r["section"] == "later"]
        # The 2-for-80 campaign of 5007899 runs again from 2026-10-26, so it is dated from the
        # next slot (2026-10-31). 5016248 has a new 98.00 price next week and an 82.00 plain
        # price cut (ProductCampaignDiscount, no MinQuantity) that starts 2026-10-26.
        self.assertEqual(sorted((r["valid_from"], r["pack"], r["price_dkk"], r["note"],
                                 r["delivery_slot"]) for r in later),
                         [("2026-10-31", "24 x 0.33 L cans", "82.0", "next week, nemlig slot",
                           "2026103114-60-240, zone 1"),
                          ("2026-10-31", "24 x 0.33 L cans", "98.0", "next week, nemlig slot",
                           "2026103114-60-240, zone 1"),
                          ("2026-10-31", "6 x 0.33 L cans, 2 for 80.00", "40.0",
                           "next week, nemlig slot", "2026103114-60-240, zone 1")])
        self.assertIn("Next week's nemlig prices listed (not in history): 3", summary)
        # Next week's prices and the slot never reach history.csv.
        rows = load_history(self.history)
        self.assertNotIn("slot", rows[0])
        self.assertFalse([r for r in rows if r["valid_from"] == "2026-10-31"])

    def test_good_offers_flag_summary_and_notification(self):
        code, summary = self.run_cli("2026-10-24")
        self.assertEqual(code, 0, summary)
        # data/products.json: Pepsi Max under 10 kr/L. 365discount and Bilka are both 9.47.
        self.assertIn("Good offers: 2\n", summary)
        self.assertIn("Notification: 2 good offers: 365discount 9.47, Bilka 9.47\n", summary)
        flags = {(r["store"], r["flag"]) for r in self.report_rows() if r["flag"]}
        self.assertEqual(flags, {("365discount", "good offer: under 10 kr/L"),
                                 ("Bilka", "good offer: under 10 kr/L")})
        html = self.report_html()
        self.assertEqual(html.count('<tr class="good">'), 2)
        self.assertIn("<th>Flag</th>", html)
        self.assertIn("Offers kept: Pepsi Max: 9, Cult Energy: 0", summary)

    def test_no_good_offers_still_gives_a_notification_line(self):
        code, summary = self.run_cli("2026-10-24", self.with_limits(self.fixture([
            tjek("p", "Pepsi Max", "6 x 33 cl ds", 25.0)])))
        self.assertIn("Good offers: 0\n", summary)
        self.assertIn("Notification: no good offers\n", summary)

    def test_below_average_flag_after_four_weeks(self):
        # Mean 12.0 over four weeks; 10.5 kr/L is not under the fixed 10, but 12.5% below 12.
        self.seed([("2026-09-28", "12"), ("2026-10-05", "12"), ("2026-10-12", "12"),
                   ("2026-10-19", "12")])
        rows = [tjek("p", "Pepsi Max", "6 x 33 cl ds", 20.79)]  # 20.79 / 1.98 L = 10.5 kr/L
        code, summary = self.run_cli("2026-10-24", self.with_limits(self.fixture(rows)))
        flagged = [r for r in self.report_rows() if r["flag"]]
        self.assertEqual([r["flag"] for r in flagged],
                         ["good offer: 10% or more below the 12-week average"])

    def test_report_md_is_written_with_the_asked_sections(self):
        md = os.path.join(self.tmp, "REPORT.md")
        code, summary = self.run_cli("2026-10-24", report_md=md)
        with open(md, encoding="utf-8") as f:
            text = f.read()
        for heading in ("# Pepsi Max and Cult Energy prices", "## Notification", "## Cheapest now",
                        "## Good offers", "## Available now", "## Starts later", "## Coverage",
                        "## Weekly low per store (kr/L)"):
            self.assertIn(heading, text)
        self.assertIn("Run date: 2026-10-24", text)
        self.assertIn("Last successful collection: 2026-10-24 (0 days before this run)", text)
        self.assertIn("2 good offers: 365discount 9.47, Bilka 9.47", text)
        self.assertIn("| Chain | Accepted |", text)
        self.assertIn("Lidl | not seen this run |", text)
        self.assertIn("| Pepsi Max | 365discount |", text.replace("  ", " "))
        # The phone report is compact: no HTML and no per-row offer text.
        self.assertNotIn("<", text)
        self.assertTrue(text.endswith("\n"))

    def test_report_md_offer_tables_carry_the_delivery_slot(self):
        md = os.path.join(self.tmp, "REPORT.md")
        self.run_cli("2026-10-24", report_md=md)
        with open(md, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("| Flag | Slot |", text)
        self.assertIn("| 2026102414-60-240, zone 1 |", text)
        self.assertIn("| 2026103114-60-240, zone 1 |", text)

    def test_offline_run_writes_no_report_md_by_default(self):
        # The repo-root REPORT.md is committed, so the run must leave it exactly as it was
        # (content and mtime), or leave it absent if there is none.
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "REPORT.md")

        def snapshot():
            if not os.path.exists(path):
                return None
            with open(path, "rb") as f:
                return f.read(), os.stat(path).st_mtime_ns

        before = snapshot()
        self.run_cli("2026-10-24")
        self.assertEqual(snapshot(), before)

    def partial_fixtures(self):
        partial = os.path.join(self.tmp, "partial")
        if not os.path.isdir(partial):
            os.mkdir(partial)
            for name in ("tjek_pepsi_max.json", "tjek_cult.json", "tjek_pepsi.json"):
                shutil.copy(os.path.join(FIXTURES, name), partial)
        return partial

    def test_last_success_survives_failed_runs_and_drives_the_warning(self):
        ls = os.path.join(self.tmp, "last_success.txt")
        md = os.path.join(self.tmp, "REPORT.md")
        # Good run: the date is recorded.
        code, summary = self.run_cli("2026-10-05", last_success=ls)
        self.assertEqual(code, 0, summary)
        with open(ls, encoding="utf-8") as f:
            self.assertEqual(f.read(), "2026-10-05\n")
        # Partial failure a week later: not a success, the date stays, no warning yet.
        code, summary = self.run_cli("2026-10-12", self.partial_fixtures(), last_success=ls)
        self.assertEqual(code, 2)
        self.assertIn("Last successful collection: 2026-10-05 (7 days before this run)", summary)
        self.assertNotIn("WARNING", summary)
        # Another failure 19 days after the good run: the warning counts from the good date.
        code, summary = self.run_cli("2026-10-24", self.partial_fixtures(), report_md=md,
                                     last_success=ls)
        self.assertEqual(code, 2)
        self.assertIn("Last successful collection: 2026-10-05 (19 days before this run)", summary)
        self.assertIn("WARNING: the last successful collection is 19 days old", summary)
        self.assertIn("WARNING", self.report_html())
        with open(md, encoding="utf-8") as f:
            self.assertIn("WARNING", f.read())
        with open(ls, encoding="utf-8") as f:
            self.assertEqual(f.read(), "2026-10-05\n")

    def test_a_run_with_zero_offers_and_no_errors_is_a_success(self):
        ls = os.path.join(self.tmp, "last_success.txt")
        with open(ls, "w", encoding="utf-8") as f:
            f.write("2026-09-01\n")
        code, summary = self.run_cli("2026-10-24", self.fixture([]), last_success=ls)
        self.assertEqual(code, 0, summary)
        self.assertIn("Offers kept: Pepsi Max: 0, Cult Energy: 0", summary)
        self.assertIn("Last successful collection: 2026-10-24 (0 days before this run)", summary)
        with open(ls, encoding="utf-8") as f:
            self.assertEqual(f.read(), "2026-10-24\n")

    def test_no_last_success_file_and_a_failed_run_means_none_on_record(self):
        code, summary = self.run_cli("2026-10-24", self.partial_fixtures(),
                                     last_success=os.path.join(self.tmp, "last_success.txt"))
        self.assertIn("Last successful collection: none on record before this run", summary)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "last_success.txt")))

    def test_a_garbled_last_success_file_stops_the_run(self):
        ls = os.path.join(self.tmp, "last_success.txt")
        with open(ls, "w", encoding="utf-8") as f:
            f.write("last tuesday\n")
        buf = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(buf), contextlib.redirect_stderr(err):
            code = main(["--offline", FIXTURES, "--history", self.history, "--out", self.out,
                         "--today", "2026-10-24", "--last-success", ls])
        self.assertEqual(code, 1)
        self.assertIn("Cannot read last success file", err.getvalue())

    def test_weekly_low_view_leaves_missing_weeks_blank(self):
        self.seed([("2026-10-05", "9"), ("2026-10-19", "11")])
        self.run_cli("2026-10-24", self.fixture([tjek("p", "Pepsi Max", "6 x 33 cl ds", 25.0)]))
        html = self.report_html()
        view = html[html.index("<h2>Weekly low per store</h2>"):html.index("<h2>Quarantine</h2>")]
        self.assertIn("<th>W41</th>", view)
        row = view[view.index("<td>SeedStore</td>"):]
        row = row[:row.index("</tr>")]
        cells = [c for c in row.split("<td") if c][1:]
        self.assertEqual(len(cells), 12)
        self.assertEqual(sum('>9.00<' in c or '>11.00<' in c for c in cells), 2)
        self.assertEqual(sum('></td>' in c for c in cells), 10)

    def test_price_per_can(self):
        code, summary = self.run_cli("2026-10-24")
        self.assertEqual(code, 0, summary)
        by = {(r["store"], r["pack"]): r["kr_per_can"] for r in self.report_rows()
              if r["status"] == "offer"}
        # 75 kr for 24 cans is 3.125, rounded half up; "2 for 80" is 40 kr for 6 cans.
        self.assertEqual(by[("365discount", "24 x 0.33 L cans")], "3.13")
        self.assertEqual(by[("nemlig.com", "6 x 0.33 L cans, 2 for 80.00")], "6.67")
        self.assertIn("<th>kr/can</th>", self.report_html())
        self.assertIn("3.13", self.report_html())

    def test_starts_later_is_split_from_available_now(self):
        # On 2026-10-24 REMA's offer valid from 2026-10-29 is not for sale yet.
        products = [rema(211240, "PEPSI MAX", "33 CL. DÅSE", 6.89, 1, 20.88),
                    rema(211241, "PEPSI MAX", "33 CL. DÅSE", 3.00, 1, 9.09,
                         starting="2026-10-28T23:00:00+00:00")]
        fx = self.fixture(SYNTHETIC_TJEK[:2], products)
        code, summary = self.run_cli("2026-10-24", fx)
        self.assertEqual(code, 0, summary)
        offers = [r for r in self.report_rows() if r["status"] == "offer"]
        later = [r for r in offers if r["section"] == "later"]
        self.assertEqual([(r["store"], r["valid_from"]) for r in later],
                         [("REMA 1000", "2026-10-29")])
        now = [r for r in offers if r["section"] == "available"]
        self.assertEqual({r["store"] for r in now}, {"Netto", "føtex", "REMA 1000"})
        self.assertNotIn("2026-10-29", {r["valid_from"] for r in now})
        # Each section is sorted by kr/L; the cheap later row does not lead the list.
        kr = [float(r["kr_per_l"]) for r in now]
        self.assertEqual(kr, sorted(kr))
        # Section order in the CSV and the HTML.
        self.assertEqual([r["section"] for r in offers], ["available"] * 3 + ["later"])
        html = self.report_html()
        self.assertLess(html.index("<h2>Available now</h2>"), html.index("<h2>Starts later</h2>"))
        self.assertLess(html.index("<h2>Starts later</h2>"), html.index("<h2>Quarantine</h2>"))
        later_html = html[html.index("<h2>Starts later</h2>"):html.index("<h2>Coverage</h2>")]
        self.assertIn("2026-10-29", later_html)
        self.assertNotIn("føtex", later_html)

    def test_cheapest_current_price_shows_its_end_date(self):
        code, summary = self.run_cli("2026-10-24", self.fixture(SYNTHETIC_TJEK[:2]))
        html = self.report_html()
        # føtex 8.00 kr/L is the cheapest Pepsi Max; its flyer ends on 2026-10-29.
        self.assertIn("Cheapest now, Pepsi Max: 8.00 kr/L at føtex, valid to 2026-10-29", html)

    def test_pepsi_query_rows_regular_pepsi_rejected_variants_listed(self):
        pepsi = [tjek("reg", "Pepsi", "24 x 33 cl ds. + pant", 70.0, store="Lidl"),
                 SYNTHETIC_TJEK[2]]
        code, summary = self.run_cli("2026-10-24", self.fixture([], pepsi_rows=pepsi))
        self.assertEqual(code, 0, summary)
        self.assertIn("Rejected Pepsi/Cult rows: 1 (regular Pepsi, not Pepsi Max: 1)", summary)
        self.assertIn("Listed as 'variants, Max likely' (not in history): 1", summary)
        self.assertEqual(load_history(self.history), [])
        self.assertEqual([r["store"] for r in self.report_rows() if r["status"] == "offer"],
                         ["SPAR"])

    def test_one_week_of_history_shows_lowest_seen_so_far(self):
        self.seed([("2026-10-12", "9")])
        code, summary = self.run_cli("2026-10-24", self.fixture(SYNTHETIC_TJEK[:2]))
        self.assertIn("Pepsi Max lowest seen so far: 9.00 kr/L (1 week sampled)", summary)
        self.assertIn("Cult Energy not enough history yet", summary)
        self.assertEqual(set(self.vs().values()), {""})

    def test_coverage_lists_chains_and_flags_unseen_ones(self):
        rows = SYNTHETIC_TJEK[:4] + [
            tjek("q", "Pepsi Max Xtreme Edition", "6 x 33 cl ds", 15.84, store="Netto")]
        code, summary = self.run_cli("2026-10-24", self.fixture(rows))
        self.assertIn("Coverage: 3 of 21 chains seen; not seen this run: ", summary)
        html = self.report_html()
        cov = html[html.index("<h2>Coverage</h2>"):]
        cov = cov[:cov.index("<h2>Quarantine</h2>")]
        # Netto: a, the bottle and the quarantined Xtreme row; føtex: b; SPAR: the variant.
        self.assertIn("<td>Netto</td>" + '<td class="num">1</td>' * 1 + '<td class="num">0</td>'
                      '<td class="num">1</td><td class="num">1</td>', cov)
        self.assertIn("<td>Lidl</td><td colspan=\"4\" class=\"muted\">not seen this run</td>", cov)
        self.assertNotIn("<td>Netto</td><td colspan", cov)
        self.assertLess(html.index("<h2>Coverage</h2>"), html.index("<h2>Quarantine</h2>"))

    def test_source_errors_stay_out_of_coverage(self):
        partial = os.path.join(self.tmp, "partial")
        os.mkdir(partial)
        for name in ("tjek_pepsi_max.json", "tjek_cult.json", "tjek_pepsi.json"):
            shutil.copy(os.path.join(FIXTURES, name), partial)
        code, summary = self.run_cli("2026-10-24", fixtures=partial)
        self.assertEqual(code, 2)
        coverage = [l for l in summary.splitlines() if l.startswith("Coverage:")]
        self.assertEqual(len(coverage), 1)
        self.assertNotIn("rema_page", coverage[0])
        self.assertEqual(len([l for l in summary.splitlines() if l.startswith("Source errors:")]), 1)


NEMLIG_PRODUCT = os.path.join(FIXTURES, "nemlig_product_5007899.json")
NEXT_SLOT = "2026103114-60-240, zone 1"


class NextWeekNemligTest(unittest.TestCase):
    """Next week's nemlig slot: dating, and what is reported from that pass."""
    known = {"nemlig": {"Pepsi Max": {"5007899", "9", "10"}, "Cult Energy": set()}}

    def build_next(self, products):
        from dealfinder.pipeline import build
        return build([], [], date(2026, 10, 24), "run", [], self.known, "", products, NEXT_SLOT)

    def test_a_campaign_already_running_is_dated_from_the_next_slot(self):
        with open(NEMLIG_PRODUCT, encoding="utf-8") as f:
            product = json.load(f)
        # The campaign began on 2026-10-21, before the run, and runs through next week.
        product["Campaign"]["IntervalStart"] = "2026-10-20T22:00:00Z"
        product["Campaign"]["IntervalEnd"] = "2026-11-01T22:59:59Z"
        outcome = self.build_next([product])
        self.assertEqual(outcome.observations, [])
        by_pack = {o.pack: o.valid_from for o in outcome.upcoming}
        self.assertEqual(len(by_pack), 2)
        self.assertEqual(set(by_pack.values()), {"2026-10-31"})

    def test_errors_quarantines_and_counts_from_next_week_are_reported(self):
        bad = {"Id": "9", "Name": "Pepsi Max", "Description": "24 x 33 cl", "Availability": "yes"}
        bottle = {"Id": "10", "Name": "Pepsi Max", "Description": "1,5 liter. + pant",
                  "Price": 12.0, "Availability": {"IsAvailableInStock": True,
                                                  "IsDeliveryAvailable": True}}
        sold_out = {"Id": "5007899", "Name": "Pepsi Max", "Description": "24 x 33 cl",
                    "Price": 100.0, "Availability": {"IsAvailableInStock": False,
                                                     "IsDeliveryAvailable": True}}
        outcome = self.build_next([bad, bottle, sold_out])
        self.assertEqual([m for _, m in outcome.row_errors],
                         ["next week: product 9 skipped: Availability is str, not an object"])
        self.assertEqual(outcome.next_week["bottles dropped"], 1)
        self.assertEqual(outcome.next_week["out of stock"], 1)
        # Not counted as this week's.
        self.assertEqual((outcome.bottles_dropped, outcome.out_of_stock), (0, 0))
        self.assertEqual((outcome.observations, outcome.upcoming), ([], []))

    def test_next_week_quarantine_is_reported(self):
        odd = {"Id": "5007899", "Name": "Pepsi Max", "Description": "24 x 33 cl", "Price": 0,
               "Availability": {"IsAvailableInStock": True, "IsDeliveryAvailable": True}}
        outcome = self.build_next([odd])
        self.assertEqual([(q.store, q.reason) for q in outcome.quarantined],
                         [("nemlig.com", "no usable price")])

    def test_next_week_problems_reach_the_run_summary_and_exit_code(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        fx = os.path.join(tmp, "fx")
        shutil.copytree(FIXTURES, fx)
        with open(os.path.join(fx, "nemlig_product_5016248_next.json"), "w", encoding="utf-8") as f:
            json.dump(["not an object"], f)
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["--offline", fx, "--history", os.path.join(tmp, "h.csv"),
                         "--out", os.path.join(tmp, "out"), "--today", "2026-10-24"])
        self.assertEqual(code, 2)
        self.assertIn("unexpected product shape for id 5016248", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
