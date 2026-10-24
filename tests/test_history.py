import os
import tempfile
import unittest
from datetime import date

from dealfinder.history import (HEADER, NOT_ENOUGH, Baseline, Observation, append_history,
                                baseline, dedupe, load_history, lowest_seen_text,
                                percent_vs)

PM = "Pepsi Max"
CULT_NAME = "Cult Energy"


def row(run_date, kr, source_id, product=PM, run_id=None, source="tjek"):
    return {"run_id": run_id or run_date + "T06:00:00Z", "run_date": run_date,
            "product": product, "source": source, "source_id": source_id,
            "kr_per_l": str(kr)}


RUN_ID = "2026-10-19T06:00:00Z"
RUN_DATE = date(2026, 10, 19)
# Four prior weekly runs (ISO weeks 39-42 of 2026) with offers a-e.
PRIOR = [
    row("2026-09-21", 9.0, "a"), row("2026-09-21", 12.0, "b"),
    row("2026-09-28", 8.0, "c"),
    row("2026-10-05", 10.0, "d"),
    row("2026-10-12", 11.0, "e"),
]


class BaselineTest(unittest.TestCase):
    """Ruling report-price-list-with-percent-vs-12-week-average-no-labels."""

    def test_mean_and_low(self):
        self.assertEqual(baseline(PRIOR, PM, RUN_ID, RUN_DATE), Baseline(10.0, 8.0, 5, 4))

    def test_offer_seen_in_two_runs_counts_once(self):
        # Offer "b" is stored again a week later; the mean stays over 5 offers, not 6.
        rows = PRIOR + [row("2026-10-12", 12.0, "b")]
        self.assertEqual(baseline(rows, PM, RUN_ID, RUN_DATE), Baseline(10.0, 8.0, 5, 4))
        # The same id from another source is a different offer.
        rows = PRIOR + [row("2026-10-12", 4.0, "b", source="rema")]
        self.assertEqual(baseline(rows, PM, RUN_ID, RUN_DATE).offers, 6)

    def test_low_survives_a_later_higher_price_for_the_same_offer(self):
        # One offer id stored at 8, 12, 16 and 20 kr/L in four weeks: the low is 8, the
        # average is still over the one distinct offer at its latest price.
        rows = [row("2026-09-21", 8.0, "z"), row("2026-09-28", 12.0, "z"),
                row("2026-10-05", 16.0, "z"), row("2026-10-12", 20.0, "z")]
        self.assertEqual(baseline(rows, PM, RUN_ID, RUN_DATE), Baseline(20.0, 8.0, 1, 4))

    def test_current_run_left_out(self):
        rows = PRIOR + [row("2026-10-19", 1.0, "now", run_id=RUN_ID)]
        self.assertEqual(baseline(rows, PM, RUN_ID, RUN_DATE), Baseline(10.0, 8.0, 5, 4))

    def test_window_is_the_12_weeks_before_the_run(self):
        # 2026-07-28 is 83 days before the run (inside); 2026-07-27 is exactly 84 (outside).
        inside = PRIOR + [row("2026-07-28", 1.0, "old")]
        self.assertEqual(baseline(inside, PM, RUN_ID, RUN_DATE).low, 1.0)
        outside = PRIOR + [row("2026-07-27", 1.0, "old")]
        self.assertEqual(baseline(outside, PM, RUN_ID, RUN_DATE), Baseline(10.0, 8.0, 5, 4))

    def test_other_product_ignored(self):
        rows = PRIOR + [row("2026-10-12", 1.0, "cult", product="Cult Energy")]
        self.assertEqual(baseline(rows, PM, RUN_ID, RUN_DATE), Baseline(10.0, 8.0, 5, 4))

    def test_not_enough_history_under_four_weeks(self):
        self.assertIsNone(baseline(PRIOR[:4], PM, RUN_ID, RUN_DATE))
        self.assertIsNone(baseline([], PM, RUN_ID, RUN_DATE))
        self.assertEqual(NOT_ENOUGH, "not enough history yet")

    def test_percent_sign_and_rounding(self):
        base = Baseline(10.0, 8.0, 5, 4)
        self.assertEqual(percent_vs(8.8, base), "-12%")
        self.assertEqual(percent_vs(10.5, base), "+5%")
        self.assertEqual(percent_vs(8.85, base), "-12%")  # -11.5 rounds away from zero
        self.assertEqual(percent_vs(10.45, base), "+5%")  # +4.5 rounds away from zero
        self.assertEqual(percent_vs(10.44, base), "+4%")
        self.assertEqual(percent_vs(10.0, base), "0%")
        self.assertEqual(percent_vs(10.04, base), "0%")


class LowestSeenTest(unittest.TestCase):
    def test_text_for_one_week(self):
        rows = [row("2026-10-12", 9.0, "a"), row("2026-10-12", 7.5, "b")]
        self.assertEqual(lowest_seen_text(rows, PM, RUN_ID, RUN_DATE),
                         "lowest seen so far: 7.50 kr/L (1 week sampled)")

    def test_text_for_three_weeks_and_no_baseline_yet(self):
        rows = PRIOR[:4]
        self.assertEqual(lowest_seen_text(rows, PM, RUN_ID, RUN_DATE),
                         "lowest seen so far: 8.00 kr/L (3 weeks sampled)")
        self.assertIsNone(baseline(rows, PM, RUN_ID, RUN_DATE))

    def test_none_without_history_and_baseline_appears_at_four_weeks(self):
        self.assertIsNone(lowest_seen_text([], PM, RUN_ID, RUN_DATE))
        self.assertIsNone(lowest_seen_text(PRIOR, CULT_NAME, RUN_ID, RUN_DATE))
        self.assertIsNotNone(baseline(PRIOR, PM, RUN_ID, RUN_DATE))


def obs(source_id, price=10.0, source="tjek", valid_from="2026-10-22"):
    return Observation(run_id=RUN_ID, run_date="2026-10-19", product=PM, source=source,
                       source_id=source_id, product_id=source_id, store="Netto", description="Pepsi Max",
                       pack="1 x 1.5 L", volume_l=1.5, price_dkk=price,
                       kr_per_l=round(price / 1.5, 2), valid_from=valid_from,
                       valid_to="2026-10-29", campaign=True, url="")


class DedupeAndStorageTest(unittest.TestCase):
    def test_slot_is_not_a_history_column(self):
        self.assertNotIn("slot", HEADER)
        self.assertEqual(HEADER[-1], "url")

    def test_within_run_dedupe(self):
        got = dedupe([obs("a"), obs("a"), obs("b"), obs("a", source="rema"), obs("a", price=12.0)])
        self.assertEqual([(o.source, o.source_id, o.price_dkk) for o in got],
                         [("tjek", "a", 10.0), ("tjek", "b", 10.0), ("rema", "a", 10.0),
                          ("tjek", "a", 12.0)])

    def test_append_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "history.csv")
            append_history(path, [obs("a")])
            append_history(path, [obs("b")])
            rows = load_history(path)
            self.assertEqual([r["source_id"] for r in rows], ["a", "b"])
            self.assertEqual(rows[0]["kr_per_l"], "6.67")
            with open(path, encoding="utf-8") as f:
                self.assertEqual(sum(1 for line in f if line.startswith("run_id,")), 1)

    def test_missing_history_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(load_history(os.path.join(d, "none.csv")), [])


if __name__ == "__main__":
    unittest.main()
