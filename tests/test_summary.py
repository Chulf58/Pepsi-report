"""The prose summary at the top of REPORT.md and report.html."""
import os
import tempfile
import unittest
from datetime import date

from dealfinder.history import Baseline, Observation
from dealfinder.match import VARIANTS_NOTE
from dealfinder.pipeline import UPCOMING_NOTE
from dealfinder.report import Extras, kr_per_can, summary_for, write_html, write_report_md

TODAY = date(2026, 10, 24)
GOOD = "good offer: under 10 kr/L"


def row(store, price, product="Pepsi Max", pack="24 x 0.33 L cans", frm="2026-10-22", to="2026-10-28",
        note="", flag="", base=None):
    liters = 7.92 if pack.startswith("24") else 0.33
    o = Observation(run_id="r", run_date="2026-10-24", product=product, source="tjek", source_id=store,
                    product_id="", store=store, description="d", pack=pack, volume_l=liters,
                    price_dkk=price, kr_per_l=round(price / liters, 2), valid_from=frm, valid_to=to,
                    campaign=True, url="")
    return o, "", base, note, flag


def summary(listed, errors=(), last_success="2026-10-24"):
    return summary_for(listed, list(errors), TODAY, Extras(last_success=last_success))


class SummaryTest(unittest.TestCase):
    def test_ties_are_one_sentence_with_both_end_dates(self):
        text = summary([row("365discount", 75, to="2026-10-28", flag=GOOD),
                        row("Bilka", 75, to="2026-10-29", flag=GOOD),
                        row("Løvbjerg", 80, to="2026-10-30")])
        self.assertIn("The cheapest Pepsi Max right now is at 365discount and Bilka: 24 x 33 cl for 75 kr, "
                      "which is 9.47 kr per liter or 3.13 kr per can, until 28 and 29 October.", text)
        self.assertIn("Both are flagged as good offers.", text)
        self.assertIn("Next is Løvbjerg at 10.10 kr/L.", text)

    def test_single_store_unflagged_and_partly_flagged(self):
        self.assertIn("It is not flagged as a good offer.", summary([row("Netto", 90)]))
        text = summary([row("A", 75, flag=GOOD), row("B", 75)])
        self.assertIn("Only A is flagged as a good offer.", text)

    def test_no_current_offers(self):
        text = summary([])
        self.assertTrue(text.startswith("No confirmed Pepsi Max offers right now."))
        self.assertNotIn("Coming up", text)

    def test_variant_rows_are_never_the_best_price(self):
        text = summary([row("Netto", 60, note=VARIANTS_NOTE), row("Bilka", 90)])
        self.assertIn("is at Bilka:", text)
        self.assertNotIn("Netto", text)
        only = summary([row("Netto", 60, note=VARIANTS_NOTE)])
        self.assertIn("No confirmed Pepsi Max offers right now; 1 listed as 'variants, Max likely' is not counted.",
                      only)

    def test_cult_absent_and_present(self):
        self.assertIn("No Cult Energy offers from Danish chains this week.", summary([row("Netto", 90)]))
        text = summary([row("Netto", 90), row("Rema 1000", 80, product="Cult Energy", to="2026-10-27")])
        self.assertNotIn("No Cult Energy", text)
        self.assertIn("The cheapest Cult Energy right now is at Rema 1000: 24 x 33 cl for 80 kr, "
                      "which is 10.10 kr per liter or 3.33 kr per can, until 27 October.", text)

    def test_cult_only_later(self):
        text = summary([row("Netto", 90), row("Rema 1000", 60, product="Cult Energy", frm="2026-10-29",
                                              to="2026-10-31")])
        self.assertIn("Cult Energy comes later: Rema 1000 has 24 x 33 cl for 60 kr (7.58 kr/L) "
                      "from 29 to 31 October.", text)

    def test_source_errors_are_named_once(self):
        text = summary([row("Netto", 90)], errors=[("tjek", "blocked"), ("tjek", "429"), ("rema", "down")])
        self.assertIn("Source errors: tjek, rema.", text)
        self.assertNotIn("All sources answered", text)
        self.assertIn("All sources answered.", summary([row("Netto", 90)]))

    def test_stale_warning_only_over_eight_days(self):
        row_ = [row("Netto", 90)]
        self.assertNotIn("Warning", summary(row_, last_success="2026-10-16"))
        self.assertIn("Warning: the last successful collection was 9 days ago.",
                      summary(row_, last_success="2026-10-15"))
        self.assertNotIn("Warning", summary(row_, last_success=""))

    def test_starts_later_rows_that_beat_next_best(self):
        now = [row("A", 75), row("B", 90)]  # next best is B at 11.36 kr/L
        later = [row("C", 80, frm="2026-10-30", to="2026-11-01"),   # 10.10: beats
                 row("D", 82, frm="2026-10-31", to="2026-10-31"),   # 10.35: beats
                 row("E", 84, frm="2026-10-29", to="2026-10-30"),   # 10.61: beats, but only 2 shown
                 row("F", 99, frm="2026-10-29", to="2026-10-30")]   # 12.50: does not beat
        text = summary(now + sorted(later, key=lambda t: t[0].kr_per_l))
        self.assertIn("Coming up: C has 24 x 33 cl for 80 kr (10.10 kr/L) from 30 October to 1 November "
                      "and D has 24 x 33 cl for 82 kr (10.35 kr/L) on 31 October.", text)
        self.assertNotIn("E has", text)

    def test_starts_later_falls_back_to_the_single_cheapest(self):
        now = [row("A", 75), row("B", 78)]  # next best 9.85 kr/L
        later = [row("C", 82, frm="2026-10-31", to=""), row("D", 99, frm="2026-10-31", to="")]
        text = summary(now + later)
        self.assertIn("Coming up: C has 24 x 33 cl for 82 kr (10.35 kr/L) from 31 October.", text)
        self.assertNotIn("D has", text)

    def test_starts_later_variants_and_upcoming_notes(self):
        text = summary([row("A", 75), row("V", 40, frm="2026-10-31", note=VARIANTS_NOTE),
                        row("nemlig.com", 70, frm="2026-10-31", note=UPCOMING_NOTE)])
        self.assertIn("Coming up: nemlig.com has", text)
        self.assertNotIn("V has", text)

    def test_average_clause_needs_a_baseline(self):
        self.assertNotIn("12-week", summary([row("A", 75)]))
        base = Baseline(12.0, 8.0, 5, 4)
        below = summary([row("A", 75, base=base)])  # 9.47 against 12.00
        self.assertIn("The best Pepsi Max price is 21% below the 12-week average of 12.00 kr/L.", below)
        self.assertIn("above the 12-week average", summary([row("A", 100, base=base)]))
        self.assertIn("equal to the 12-week average", summary([row("A", 95.04, base=base)]))

    def test_short_enough_for_a_phone(self):
        text = summary([row("365discount", 75, flag=GOOD), row("Bilka", 75, flag=GOOD), row("Løvbjerg", 80),
                        row("nemlig.com", 82, frm="2026-10-31", to="2026-11-01")])
        self.assertLess(len(text.split()), 100)

    def test_deterministic(self):
        listed = [row("A", 75), row("B", 75)]
        self.assertEqual(summary(listed), summary(listed))

    def test_kr_per_can_is_the_report_figure(self):
        o = row("A", 75)[0]
        self.assertEqual(kr_per_can(o), 3.13)


class PackTextTest(unittest.TestCase):
    def test_pack_in_cl(self):
        from dealfinder.summary import _pack
        self.assertEqual(_pack("24 x 0.33 L cans"), "24 x 33 cl")
        self.assertEqual(_pack("0.33 L can"), "33 cl")
        self.assertEqual(_pack("odd text"), "odd text")


class SummaryEscapingTest(unittest.TestCase):
    def test_markdown_and_html_escape_the_store_name(self):
        listed = [row("Shop|<b>&", 75)]
        with tempfile.TemporaryDirectory() as tmp:
            md, page = os.path.join(tmp, "R.md"), os.path.join(tmp, "report.html")
            extras = Extras(last_success="2026-10-24")
            write_report_md(md, "run", listed, [], [], TODAY, extras)
            write_html(page, "run", listed, [], [], [], (), TODAY, extras)
            with open(md, encoding="utf-8") as f:
                lines = f.read().split("\n")
            with open(page, encoding="utf-8") as f:
                html = f.read()
        self.assertEqual(lines[0], "# Pepsi Max and Cult Energy prices")
        self.assertTrue(lines[2].startswith("The cheapest Pepsi Max right now is at Shop\\|<b>&:"))
        self.assertIn('<p class="summary">The cheapest Pepsi Max right now is at Shop|&lt;b&gt;&amp;:', html)
        self.assertLess(html.index('class="summary"'), html.index("Run run."))


if __name__ == "__main__":
    unittest.main()
