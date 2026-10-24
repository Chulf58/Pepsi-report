"""Good-offer flags, the notification text, the report age and the weekly-low view."""
import json
import os
import tempfile
import unittest
from datetime import date

from dealfinder.flags import Limits, flag_reason, flagged_offers, load_limits, toast_text
from dealfinder.history import Baseline, Observation, week_labels, weekly_lows
from dealfinder.report import Extras, age_lines

TODAY = date(2026, 10, 24)
LIMITS = Limits({"Pepsi Max": 10.0, "Cult Energy": 12.0}, 10.0)
BASE = Baseline(12.0, 8.0, 5, 4)


def obs(kr, product="Pepsi Max", store="Netto", valid_from="2026-10-22"):
    return Observation(run_id="r", run_date="2026-10-24", product=product, source="tjek",
                       source_id="x", product_id="x", store=store, description="d", pack="24 x 0.33 L cans",
                       volume_l=7.92, price_dkk=kr * 7.92, kr_per_l=kr, valid_from=valid_from,
                       valid_to="2026-10-29", campaign=True, url="")


def flag(o, note="", base=None, limits=LIMITS):
    return flag_reason(o, note, base, limits, TODAY)


class FlagTest(unittest.TestCase):
    def test_fixed_limit_is_strictly_under(self):
        self.assertEqual(flag(obs(9.99)), "good offer: under 10 kr/L")
        self.assertEqual(flag(obs(10.0)), "")
        self.assertEqual(flag(obs(11.99, product="Cult Energy")), "good offer: under 12 kr/L")
        self.assertEqual(flag(obs(12.0, product="Cult Energy")), "")

    def test_below_average_needs_ten_percent_and_a_baseline(self):
        # Average 12.0: 10.8 is exactly 10% below, 10.9 is not.
        self.assertEqual(flag(obs(10.8), base=BASE),
                         "good offer: 10% or more below the 12-week average")
        self.assertEqual(flag(obs(10.9), base=BASE), "")
        self.assertEqual(flag(obs(10.8), base=None), "")

    def test_both_rules_give_one_flag(self):
        self.assertEqual(flag(obs(9.0), base=BASE),
                         "good offer: under 10 kr/L, 10% or more below the 12-week average")

    def test_variants_and_next_week_rows_are_never_flagged(self):
        self.assertEqual(flag(obs(5.0), note="variants, Max likely"), "")
        self.assertEqual(flag(obs(5.0), note="next week, nemlig slot"), "")

    def test_offer_not_valid_yet_is_not_flagged(self):
        self.assertEqual(flag(obs(5.0, valid_from="2026-10-25")), "")
        self.assertNotEqual(flag(obs(5.0, valid_from="2026-10-24")), "")

    def test_no_configured_limits_flag_nothing(self):
        self.assertEqual(flag(obs(1.0), base=BASE, limits=Limits()), "")


class ToastTest(unittest.TestCase):
    def listed(self, *offers):
        return [(o, "", None, "", flag(o)) for o in offers]

    def test_names_the_flagged_offers_cheapest_first(self):
        flagged = flagged_offers(self.listed(obs(10.1, store="Løvbjerg"), obs(9.47, store="365discount"),
                                             obs(9.0, product="Pepsi Max", store="Netto")))
        self.assertEqual(toast_text(flagged), "2 good offers: Netto 9.00, 365discount 9.47")

    def test_singular_and_none(self):
        self.assertEqual(toast_text(flagged_offers(self.listed(obs(9.47, store="365discount")))),
                         "1 good offer: 365discount 9.47")
        self.assertEqual(toast_text(flagged_offers(self.listed(obs(15.0)))), "no good offers")


class LimitsFileTest(unittest.TestCase):
    def load(self, data):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "products.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            return load_limits(path)

    def test_limits_come_from_the_file(self):
        got = self.load({"good_offer": {"max_kr_per_l": {"Pepsi Max": 9, "Cult Energy": 11},
                                        "below_average_percent": 15}})
        self.assertEqual(got, Limits({"Pepsi Max": 9.0, "Cult Energy": 11.0}, 15.0))

    def test_missing_key_means_no_limits_and_bad_values_are_refused(self):
        self.assertEqual(self.load({}), Limits())
        with self.assertRaises(ValueError):
            self.load({"good_offer": {"max_kr_per_l": {"Pepsi Max": -1}}})
        with self.assertRaises(ValueError):
            self.load({"good_offer": {"below_average_percent": "ten"}})


class AgeTest(unittest.TestCase):
    def lines(self, last):
        return age_lines(Extras(last_success=last), TODAY)

    def test_warns_only_past_eight_days(self):
        self.assertEqual(self.lines("2026-10-16"),  # 8 days: no warning
                         ["Last successful collection: 2026-10-16 (8 days before this run)"])
        warned = self.lines("2026-10-15")  # 9 days
        self.assertEqual(len(warned), 2)
        self.assertIn("WARNING", warned[1])
        self.assertIn("9 days old", warned[1])

    def test_today_and_none_on_record(self):
        self.assertEqual(self.lines("2026-10-24"),
                         ["Last successful collection: 2026-10-24 (0 days before this run)"])
        self.assertEqual(self.lines(""), ["Last successful collection: none on record before this run"])


class WeeklyLowTest(unittest.TestCase):
    def row(self, day, kr, store="Netto", product="Pepsi Max"):
        return {"run_date": day, "kr_per_l": str(kr), "store": store, "product": product}

    def test_minimum_per_store_and_week_with_blank_weeks(self):
        rows = [self.row("2026-10-24", 9.5), self.row("2026-10-23", 8.0),  # same ISO week 43
                self.row("2026-10-10", 11.0),  # week 41; week 42 stays blank
                self.row("2026-10-24", 15.0, store="Lidl"),
                self.row("2026-10-24", 3.0, product="Cult Energy"),
                self.row("2025-01-01", 1.0)]  # outside the 12 weeks
        got = weekly_lows(rows, TODAY)
        self.assertEqual(got["Pepsi Max"], {"Netto": {"W43": 8.0, "W41": 11.0}, "Lidl": {"W43": 15.0}})
        self.assertEqual(got["Cult Energy"], {"Netto": {"W43": 3.0}})
        self.assertNotIn("W42", got["Pepsi Max"]["Netto"])

    def test_labels_cover_12_weeks_oldest_first(self):
        labels = week_labels(TODAY)
        self.assertEqual((len(labels), labels[0], labels[-1]), (12, "W32", "W43"))
        self.assertEqual(week_labels(date(2026, 1, 8))[0], "25-W43")


if __name__ == "__main__":
    unittest.main()
