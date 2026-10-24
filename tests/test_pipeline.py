import csv
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout

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


def rema(pid, name, underline, price, deposit, compare, ending="2026-10-31T00:00:00+00:00"):
    entry = {"price": price, "is_campaign": True, "starting_at": "2026-10-22T00:00:00+00:00",
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

    def fixture(self, tjek_rows, rema_products=()):
        d = os.path.join(self.tmp, "fx")
        os.makedirs(d, exist_ok=True)
        for name, rows in (("tjek_pepsi_max.json", tjek_rows), ("tjek_cult.json", [])):
            with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                json.dump(rows, f)
        with open(os.path.join(d, "rema_page_1.json"), "w", encoding="utf-8") as f:
            json.dump({"data": list(rema_products), "meta": {"pagination": {"last_page": 1}}}, f)
        # No confirmed ids and no nemlig products, so only the text rules apply.
        with open(os.path.join(d, "products.json"), "w", encoding="utf-8") as f:
            json.dump({}, f)
        return d

    def run_cli(self, today, fixtures=FIXTURES):
        buf = io.StringIO()
        products = os.path.join(fixtures, "products.json")
        extra = ["--products", products] if os.path.exists(products) else []
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
                            "product": "Pepsi Max", "source": "seed", "source_id": str(i),
                            "kr_per_l": kr})

    def test_real_fixture_run(self):
        code, summary = self.run_cli("2026-10-23")
        self.assertEqual(code, 0, summary)
        rows = load_history(self.history)
        # Cans only; under 1 L without a bottle word counts as a can.
        self.assertEqual(sorted((r["store"], r["pack"], r["kr_per_l"]) for r in rows), [
            ("365discount", "24 x 0.33 L cans", "9.47"),
            ("Løvbjerg", "24 x 0.33 L cans", "10.1"),
            ("REMA 1000", "0.33 L can", "10.61"),
            ("REMA 1000", "0.33 L can", "20.88"),
            ("REMA 1000", "6 x 0.33 L cans", "20.83"),
            ("nemlig.com", "24 x 0.33 L cans", "15.62"),
            ("nemlig.com", "6 x 0.33 L cans", "20.83"),
            ("nemlig.com", "6 x 0.33 L cans, 2 for 80.00", "20.2"),
        ])
        self.assertIn("Offers kept: Pepsi Max: 8, Cult Energy: 0", summary)
        self.assertIn("Out of stock skipped (nemlig): 1", summary)  # 5061661
        self.assertIn("Requests: nemlig 5, rema 2, tjek 6", summary)
        # Every stored row carries its source product id.
        self.assertTrue(all(r["product_id"] for r in rows))
        campaign = [r for r in rows if r["source_id"] == "5007899@campaign:2026-10-19"][0]
        self.assertEqual((campaign["price_dkk"], campaign["valid_from"], campaign["valid_to"]),
                         ("40.0", "2026-10-19", "2026-10-25"))
        # REMA ids on the confirmed list are not reported as text matches; Tjek rows are.
        self.assertIn("Matched by text, not by a confirmed id: 3", summary)
        self.assertIn("Matched by text", self.report_html())
        self.assertIn("Bottles dropped: 9", summary)
        self.assertIn("BorderShop 2", summary)
        report = self.report_rows()
        quarantined = {(r["store"], r["reason"]) for r in report if r["status"] == "quarantine"}
        self.assertIn(("Bilka", "several pack sizes in text: 5.94, 7.92 L"), quarantined)
        self.assertIn(("Løvbjerg", "alternative pack counts in text (/6/20 ds)"), quarantined)
        self.assertEqual(len([r for r in report if r["status"] == "quarantine"]), 2)
        stores = {r["store"] for r in report}
        self.assertFalse(stores & {"Netto", "SuperBrugsen", "Kvickly", "MENY", "BorderShop"})
        self.assertEqual({r["vs_12w_avg"] for r in report if r["status"] == "offer"},
                         {"not enough history yet"})
        kr = [float(r["kr_per_l"]) for r in report if r["status"] == "offer"]
        self.assertEqual(kr, sorted(kr))
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
        self.assertEqual(vs["Bilka"], "not enough history yet")  # Cult has no history
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
        self.assertEqual(set(self.vs().values()) - {""}, {"not enough history yet"})
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
        for name in ("tjek_pepsi_max.json", "tjek_cult.json"):
            shutil.copy(os.path.join(FIXTURES, name), partial)
        code, summary = self.run_cli("2026-10-23", fixtures=partial)
        self.assertEqual(code, 2)
        self.assertIn("REMA", summary)
        html = self.report_html()
        self.assertIn('<h2 class="err">Source errors', html)
        self.assertIn("rema_page_1.json", html)
        # Tjek observations are still recorded.
        self.assertTrue(load_history(self.history))


if __name__ == "__main__":
    unittest.main()
