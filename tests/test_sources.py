import unittest
from datetime import date

import json
import os
import tempfile

from dealfinder.match import load_known_ids
from dealfinder.pipeline import Outcome, normalize_nemlig, normalize_rema, normalize_tjek
from dealfinder.report import csv_safe, link_html
from dealfinder.sources import (NEMLIG_MAX_IDS, NEMLIG_PASSES, USER_AGENT, SourceError, fetch_nemlig,
                                fetch_nemlig_weeks, fetch_rema, fetch_tjek, next_week_slot)


class StubTransport:
    def __init__(self, error):
        self.error = error
        self.calls = 0

    def get_json(self, source, url, fixture):
        self.calls += 1
        raise self.error


class TjekBlockTest(unittest.TestCase):
    def test_block_stops_all_tjek_requests(self):
        stub = StubTransport(SourceError("HTTP 429 for x", blocked=True))
        offers, errors = fetch_tjek(stub)
        self.assertEqual((offers, stub.calls), ([], 1))
        self.assertEqual(errors, [("Tjek", "HTTP 429 for x")])

    def test_other_errors_are_reported_per_request_without_retry(self):
        stub = StubTransport(SourceError("request failed"))
        offers, errors = fetch_tjek(stub)
        self.assertEqual(stub.calls, 9)  # 3 queries x 3 centres, one attempt each
        self.assertEqual(len(errors), 9)

    def test_request_count_is_capped_at_27(self):
        class Full:
            fixtures, calls = [], 0

            def get_json(self, source, url, fixture):
                self.calls += 1
                self.fixtures.append(fixture)
                return [{"id": "x%d" % self.calls}] * 100
        full = Full()
        offers, errors = fetch_tjek(full)
        self.assertEqual(full.calls, 27)  # 3 queries x 3 centres x 3 pages, no early stop
        self.assertEqual(sorted(set(full.fixtures)),
                         ["tjek_cult.json", "tjek_pepsi.json", "tjek_pepsi_max.json"])
        self.assertEqual(len(errors), 9)

    def test_short_page_stops_early_for_each_query_and_centre(self):
        class Short:
            calls = 0

            def get_json(self, source, url, fixture):
                self.calls += 1
                return [{"id": "x"}]
        short = Short()
        offers, errors = fetch_tjek(short)
        self.assertEqual((short.calls, errors), (9, []))

    def test_user_agent_has_no_personal_data(self):
        self.assertNotRegex(USER_AGENT, r"@|mailto:")
        self.assertIn("PepsiReport", USER_AGENT)

    def test_nemlig_block_stops_the_source(self):
        stub = StubTransport(SourceError("redirected to queue-it", blocked=True))
        products, errors = fetch_nemlig(stub, ["5007899", "5016248"])
        self.assertEqual((products, stub.calls), ([], 1))
        self.assertEqual(errors, [("nemlig", "redirected to queue-it")])

    def test_nemlig_block_on_a_product_stops_the_rest(self):
        class Seq:
            calls = 0

            def get_json(self, source, url, fixture):
                self.calls += 1
                if fixture == "nemlig_settings.json":
                    return {"ProductsImportedTimestamp": "T"}
                if fixture == "nemlig_basket.json":
                    return {"TimeslotUtc": "S", "DeliveryZoneId": 1}
                raise SourceError("HTTP 403 for x", blocked=True)
        seq = Seq()
        products, errors = fetch_nemlig(seq, ["1", "2", "3"])
        self.assertEqual((products, seq.calls, errors), ([], 3, [("nemlig", "HTTP 403 for x")]))

    def test_rema_error_reported(self):
        stub = StubTransport(SourceError("HTTP 500 for y"))
        products, errors = fetch_rema(stub)
        self.assertEqual((products, errors), ([], [("REMA", "HTTP 500 for y")]))


def offer(description, price, heading="Pepsi Max"):
    return {"id": "x1", "heading": heading, "description": description,
            "pricing": {"price": price, "currency": "DKK"},
            "quantity": {"unit": None, "size": {"from": 1, "to": 1},
                         "pieces": {"from": 1, "to": 1}},
            "run_from": "2026-10-22T22:00:00+0000", "run_till": "2026-10-29T22:59:59+0000",
            "links": {"webshop": None},
            "dealer": {"name": "Netto", "country": {"id": "DK"}, "website": "https://netto.dk"}}


class NemligNextWeekTest(unittest.TestCase):
    class Seq:
        def __init__(self):
            self.urls = []

        def get_json(self, source, url, fixture):
            self.urls.append((url, fixture))
            if fixture == "nemlig_settings.json":
                return {"ProductsImportedTimestamp": "T"}
            if fixture == "nemlig_basket.json":
                return {"TimeslotUtc": "2026102414-60-240", "DeliveryZoneId": 1}
            return {"Id": fixture}

    def test_next_slot_is_one_week_later(self):
        self.assertEqual(next_week_slot("2026102414-60-240"), "2026103114-60-240")
        self.assertEqual(next_week_slot("2026122818-60-240"), "2027010418-60-240")
        self.assertIsNone(next_week_slot("garbage"))

    def test_second_pass_reads_the_later_slot_in_the_path(self):
        seq = self.Seq()
        passes, errors = fetch_nemlig_weeks(seq, ["1", "2"], next_week=True)
        self.assertEqual(errors, [])
        self.assertEqual([slot for slot, _ in passes],
                         ["2026102414-60-240, zone 1", "2026103114-60-240, zone 1"])
        self.assertEqual(len(seq.urls), 2 + 2 + 2)  # settings, basket, two ids per slot
        self.assertIn("/T/2026102414-60-240/1/0/Products/Get", seq.urls[2][0])
        self.assertIn("/T/2026103114-60-240/1/0/Products/Get", seq.urls[4][0])
        self.assertEqual(seq.urls[4][1], "nemlig_product_1_next.json")

    def test_this_week_only_by_default(self):
        seq = self.Seq()
        passes, errors = fetch_nemlig_weeks(seq, ["1"])
        self.assertEqual((len(passes), len(seq.urls)), (1, 3))


class NemligCapTest(unittest.TestCase):
    """At most NEMLIG_MAX_IDS product requests per run, counted over both slot passes."""

    def run_fetch(self, n, next_week):
        seq = NemligNextWeekTest.Seq()
        try:
            return seq, fetch_nemlig_weeks(seq, [str(i) for i in range(n)], next_week=next_week)
        except ValueError as e:
            return seq, e

    def test_two_passes_at_the_cap_are_allowed(self):
        seq, (passes, errors) = self.run_fetch(NEMLIG_MAX_IDS // NEMLIG_PASSES, True)
        product_gets = [u for u in seq.urls if "Products/Get" in u[0]]
        self.assertEqual((len(passes), errors, len(product_gets)), (2, [], 24))

    def test_two_passes_over_the_cap_are_refused_before_any_request(self):
        seq, err = self.run_fetch(NEMLIG_MAX_IDS // NEMLIG_PASSES + 1, True)
        self.assertIsInstance(err, ValueError)
        self.assertIn("26 product requests", str(err))
        self.assertEqual(seq.urls, [])

    def test_one_pass_may_use_the_whole_cap(self):
        seq, (passes, errors) = self.run_fetch(NEMLIG_MAX_IDS, False)
        self.assertEqual((len(passes), len([u for u in seq.urls if "Products/Get" in u[0]])),
                         (1, NEMLIG_MAX_IDS))


class PantExclusionTest(unittest.TestCase):
    def run_one(self, o):
        out = Outcome()
        normalize_tjek([o], date(2026, 10, 23), "r1", out)
        return out

    def test_price_including_pant_is_reduced(self):
        out = self.run_one(offer("24 x 33 cl. ds. Pris inkl. pant", 99.0))
        o = out.observations[0]
        self.assertEqual((o.price_dkk, o.kr_per_l), (75.0, 9.47))

    def test_price_excluding_pant_unchanged(self):
        out = self.run_one(offer("24 x 33 cl ds + pant. Pr. liter 9,47", 75.0))
        self.assertEqual(out.observations[0].kr_per_l, 9.47)

    def test_unstated_pant_means_excluded(self):
        out = self.run_one(offer("6 x 33 cl ds", 15.84))
        self.assertEqual(out.observations[0].kr_per_l, 8.0)

    def test_price_not_positive_after_pant_quarantined(self):
        out = self.run_one(offer("24 x 33 cl ds inkl. pant", 20.0))
        self.assertEqual(out.observations, [])
        self.assertIn("not positive after pant", out.quarantined[0].reason)

    def test_total_volume_note_does_not_make_a_bottle(self):
        out = self.run_one(offer("24 x 0,33 l (7,92 l)", 75.0))
        self.assertEqual((out.bottles_dropped, out.observations[0].kr_per_l), (0, 9.47))

    def test_standalone_bracketed_size_counts_as_a_can(self):
        out = self.run_one(offer("Pepsi Max (0,33 l)", 6.0))
        self.assertEqual((out.bottles_dropped, out.quarantined), (0, []))
        self.assertEqual(out.observations[0].kr_per_l, 18.18)

    def test_bracketed_total_mismatch_quarantined(self):
        out = self.run_one(offer("6 x 0,33 l (2 l)", 20.0))
        self.assertEqual((out.observations, out.bottles_dropped), ([], 0))
        self.assertEqual(out.quarantined[0].reason, "several pack sizes in text: 1.98, 2 L")

    def test_bottle_dropped(self):
        out = self.run_one(offer("1,5 liter. Inkl. pant", 15.0))
        self.assertEqual((out.observations, out.quarantined, out.bottles_dropped), ([], [], 1))

    def test_no_container_word_under_1_l_is_a_can(self):
        out = self.run_one(offer("24 x 33 cl inkl. pant", 99.0))
        self.assertEqual(out.observations[0].price_dkk, 75.0)

    def test_unknown_container_quarantined(self):
        out = self.run_one(offer("24 x 33 cl dåser eller glas inkl. pant", 99.0))
        self.assertEqual(out.observations, [])
        self.assertIn("container unknown", out.quarantined[0].reason)

    def test_border_shop_excluded(self):
        o = offer("24 x 33 CL ds", 59.95)
        o["dealer"]["name"] = "BorderShop"
        out = self.run_one(o)
        self.assertEqual((out.observations, dict(out.excluded_dealers)), ([], {"BorderShop": 1}))

    def test_bad_run_till_is_a_row_error(self):
        o = offer("6 x 33 cl ds", 15.84)
        o["run_till"] = "2026-10-32T22:59:59+0000"
        out = self.run_one(o)
        self.assertEqual(out.observations, [])
        self.assertEqual(len(out.row_errors), 1)
        self.assertEqual(out.row_errors[0][0], "Tjek")


def nemlig_product(campaign=None, stock=True, delivery=True):
    return {"Id": "5007899", "Name": "Pepsi Max (dåse)",
            "Description": "6 x 0,33 l / ex. pant / indh. sødestoffer / Pepsi", "Price": 41.25,
            "Campaign": campaign,
            "Availability": {"IsAvailableInStock": stock, "IsDeliveryAvailable": delivery},
            "Url": "pepsi-max-daase-5007899"}


def mix(count, total):
    return {"Type": "ProductCampaignMixOffer", "MinQuantity": count, "CampaignPrice": total,
            "VariousPriceProductsCampaign": False,
            "IntervalStart": "2026-10-18T22:00:00Z", "IntervalEnd": "2026-10-25T21:59:59Z"}


class NemligRowTest(unittest.TestCase):
    def run_one(self, p):
        out = Outcome(known={"nemlig": {"Pepsi Max": {"5007899"}}})
        normalize_nemlig([p], date(2026, 10, 23), "r1", out)
        return out

    def test_mix_offer_gives_normal_and_per_pack_campaign_rows(self):
        out = self.run_one(nemlig_product({
            "Type": "ProductCampaignMixOffer", "MinQuantity": 2, "CampaignPrice": 80.0,
            "VariousPriceProductsCampaign": False,
            "IntervalStart": "2026-10-18T22:00:00Z", "IntervalEnd": "2026-10-25T21:59:59Z"}))
        normal, camp = out.observations
        self.assertEqual((normal.price_dkk, normal.kr_per_l, normal.campaign), (41.25, 20.83, False))
        self.assertEqual((camp.price_dkk, camp.kr_per_l, camp.campaign), (40.0, 20.2, True))
        self.assertEqual((camp.valid_from, camp.valid_to), ("2026-10-19", "2026-10-25"))
        self.assertEqual(camp.pack, "6 x 0.33 L cans, 2 for 80.00")
        self.assertEqual(out.text_matched, [])

    def test_listed_cult_id_is_kept_as_cult_energy(self):
        # Synthetic product (nemlig lists no Cult Energy on 2026-10-24): the id, not
        # the name, decides the product, so a name without the word "Cult" still counts.
        p = nemlig_product()
        p.update({"Id": "9990001", "Name": "Energidrik (dåse)",
                  "Description": "24 x 0,25 l / ex. pant", "Price": 120.0,
                  "Url": "energidrik-daase-9990001"})
        out = Outcome(known={"nemlig": {"Cult Energy": {"9990001"}}})
        normalize_nemlig([p], date(2026, 10, 23), "r1", out)
        (obs,) = out.observations
        self.assertEqual((obs.product, obs.source_id, obs.price_dkk), ("Cult Energy", "9990001", 120.0))
        self.assertEqual(out.text_matched, [])

    def test_unclear_campaign_quarantined(self):
        out = self.run_one(nemlig_product({
            "Type": "X", "MinQuantity": 0, "CampaignPrice": 80.0,
            "IntervalStart": "2026-10-18T22:00:00Z", "IntervalEnd": "2026-10-25T21:59:59Z"}))
        self.assertEqual(len(out.observations), 1)
        self.assertIn("campaign not understood", out.quarantined[0].reason)

    def test_out_of_stock_skipped(self):
        out = self.run_one(nemlig_product(stock=False))
        self.assertEqual((out.observations, out.out_of_stock), ([], 1))

    def test_not_deliverable_skipped(self):
        out = self.run_one(nemlig_product(delivery=False))
        self.assertEqual((out.observations, out.out_of_stock), ([], 1))
        p = nemlig_product()
        del p["Availability"]["IsDeliveryAvailable"]
        self.assertEqual(self.run_one(p).out_of_stock, 1)

    def test_campaign_price_not_rounded_before_kr_per_litre(self):
        out = self.run_one(nemlig_product(mix(3, 100.0)))
        camp = out.observations[1]
        # 100 / 3 / 1.98 = 16.835..., which rounds to 16.84 (16.83 if 33.33 were used).
        self.assertEqual((camp.price_dkk, camp.kr_per_l), (33.33, 16.84))

    def test_campaign_price_that_rounds_to_zero_quarantined(self):
        out = self.run_one(nemlig_product(mix(10000, 1.0)))
        self.assertEqual(len(out.observations), 1)  # the normal price only
        self.assertIn("no usable kr/L", out.quarantined[0].reason)

    def test_bad_nested_shapes_are_row_errors(self):
        p = nemlig_product()
        p["Availability"] = "yes"
        out = self.run_one(p)
        self.assertEqual(out.observations, [])
        self.assertIn("Availability is str", out.row_errors[0][1])
        out = Outcome()
        normalize_nemlig(["not a product"], date(2026, 10, 23), "r1", out)
        self.assertIn("not an object", out.row_errors[0][1])


class NestedShapeTest(unittest.TestCase):
    def test_tjek_country_as_text_is_a_row_error(self):
        o = offer("6 x 33 cl ds", 15.84)
        o["dealer"]["country"] = "DK"
        out = Outcome()
        normalize_tjek([o], date(2026, 10, 23), "r1", out)
        self.assertEqual(out.observations, [])
        self.assertIn("dealer.country is str", out.row_errors[0][1])

    def test_tjek_pricing_as_text_is_a_row_error(self):
        o = offer("6 x 33 cl ds", 15.84)
        o["pricing"] = "15.84"
        out = Outcome()
        normalize_tjek([o, offer("6 x 33 cl ds", 15.84)], date(2026, 10, 23), "r1", out)
        self.assertEqual((len(out.row_errors), len(out.observations)), (1, 1))

    def test_tjek_description_not_text_is_a_row_error(self):
        o = offer("6 x 33 cl ds", 15.84)
        o["description"] = 42
        out = Outcome()
        normalize_tjek([o], date(2026, 10, 23), "r1", out)
        self.assertIn("not text", out.row_errors[0][1])

    def test_rema_bad_prices_are_row_errors(self):
        good = {"id": 2, "name": "PEPSI MAX", "underline": "33 CL.", "prices": [
            {"price": 6.89, "starting_at": "2026-07-02T00:00:00+00:00",
             "ending_at": "2026-10-28T00:00:00+00:00", "deposit": 1, "compare_unit": "ltr",
             "compare_unit_price": "20.88"}]}
        products = [{"id": 1, "name": "PEPSI MAX", "underline": "33 CL.", "prices": "bad"},
                    {"id": 3, "name": "PEPSI MAX", "underline": "33 CL.", "prices": ["bad"]},
                    good]
        out = Outcome()
        normalize_rema(products, date(2026, 10, 23), "r1", out)
        self.assertEqual(len(out.row_errors), 2)
        self.assertIn("prices is str", out.row_errors[0][1])
        self.assertIn("price entry is str", out.row_errors[1][1])
        # A text compare_unit_price is ignored, not a crash.
        self.assertEqual(out.observations[0].kr_per_l, 20.88)


class ProductListTest(unittest.TestCase):
    def load(self, data):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "products.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            return load_known_ids(path)

    def test_id_under_two_products_refused(self):
        with self.assertRaisesRegex(ValueError, "both products: 7"):
            self.load({"rema": {"Pepsi Max": ["7", "8"], "Cult Energy": ["7"]}})

    def test_too_many_nemlig_ids_refused(self):
        # The cap counts product requests over both slot passes: 12 ids = 24 requests.
        top = NEMLIG_MAX_IDS // NEMLIG_PASSES
        ids = [str(i) for i in range(top + 1)]
        with self.assertRaisesRegex(ValueError, "more than the cap"):
            self.load({"nemlig": {"Pepsi Max": ids}})
        self.assertEqual(len(self.load({"nemlig": {"Pepsi Max": ids[:-1]}})["nemlig"]["Pepsi Max"]),
                         top)

    def test_fetch_refuses_over_cap_before_any_request(self):
        stub = StubTransport(SourceError("never"))
        with self.assertRaises(ValueError):
            fetch_nemlig(stub, [str(i) for i in range(NEMLIG_MAX_IDS + 1)])
        self.assertEqual(stub.calls, 0)


class ReportSafetyTest(unittest.TestCase):
    def test_link_only_for_http(self):
        self.assertEqual(link_html("https://netto.dk/x?a=1&b=2"),
                         '<a href="https://netto.dk/x?a=1&amp;b=2" rel="noopener">link</a>')
        self.assertEqual(link_html("javascript:alert(1)"), "javascript:alert(1)")
        self.assertEqual(link_html("<b>x</b>"), "&lt;b&gt;x&lt;/b&gt;")

    def test_csv_safe(self):
        for raw in ("=1+1", "+45", "-3", "@SUM(A1)", "\t1", "\r1", "\n1", " =1", "\x01=1",
                    "  \t@x"):
            self.assertEqual(csv_safe(raw), "'" + raw, repr(raw))
        self.assertEqual(csv_safe(" Pepsi"), " Pepsi")
        self.assertEqual(csv_safe("Pepsi Max"), "Pepsi Max")
        self.assertEqual(csv_safe(9.47), 9.47)


if __name__ == "__main__":
    unittest.main()
