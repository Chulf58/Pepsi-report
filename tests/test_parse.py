import unittest

from datetime import date, datetime, timezone

from dealfinder.parse import (CAN, BOTTLE, container_kind, copenhagen_date,
                              fixed_rule_offset_hours, pant_per_container, pant_status,
                              parse_packs, parse_stated_kr_per_l, resolve_volume)


class VolumeParseTest(unittest.TestCase):
    def vols(self, text):
        return parse_packs(text).volumes

    def test_multipack_cl(self):
        self.assertEqual(self.vols("24 x 33 CL\nB:2122708"), [7.92])

    def test_kasse_a_liter(self):
        self.assertEqual(self.vols("Kasse à 12 x 0,5 liter Liter = kr. 11,50"), [6.0])

    def test_ltr_with_dot(self):
        self.assertEqual(self.vols("1.5 LTR."), [1.5])

    def test_rema_total_pack(self):
        self.assertEqual(self.vols("1.98 LTR. / 6 PK."), [1.98])

    def test_cans_slash_count(self):
        self.assertEqual(self.vols("33 cl/24 ds\nPr ltr 10,10\nExcl pant"), [7.92])

    def test_total_in_brackets_agrees(self):
        self.assertEqual(self.vols("6 x 1,5 l (9 l)\n1 l = 5,33 DKK | 0,71 €"), [9.0])

    def test_per_litre_price_not_a_volume(self):
        self.assertEqual(self.vols("2 liter. + pant.\nPr. liter 8,00\n2 LITER"), [2.0])
        self.assertEqual(self.vols("Pr. liter 7,95. Ingen pant."), [])

    def test_several_sizes_listed(self):
        self.assertEqual(self.vols("18x33 cl. ds. Royal Export. 24x33 cl. ds. Pepsi Max"),
                         [5.94, 7.92])

    def test_range_is_ambiguous(self):
        self.assertIsNotNone(parse_packs("27,5-33 cl. Flere varianter.").ambiguous)

    def test_alternative_counts_are_ambiguous(self):
        self.assertIsNotNone(parse_packs("33 cl/6/20 ds el. 50 cl/8 ds").ambiguous)

    def test_total_note_in_brackets_is_not_a_container(self):
        parsed = parse_packs("24 x 0,33 l (7,92 l)")
        self.assertEqual(parsed.volumes, [7.92])
        self.assertEqual(parsed.container_sizes, [0.33])
        self.assertEqual(parse_packs("6 x 1,5 l (9 l)").container_sizes, [1.5])
        self.assertEqual(parse_packs("33 cl (1 stk)").container_sizes, [0.33])

    def test_standalone_bracketed_size_is_a_container(self):
        parsed = parse_packs("Pepsi Max (0,33 l)")
        self.assertEqual(parsed.container_sizes, [0.33])
        self.assertEqual(container_kind("Pepsi Max (0,33 l)", parsed.container_sizes), CAN)

    def test_bracketed_total_that_disagrees_gives_several_sizes(self):
        parsed = parse_packs("6 x 0,33 l (2 l)")
        self.assertEqual(parsed.container_sizes, [0.33])
        self.assertEqual(parsed.volumes, [1.98, 2.0])
        self.assertEqual(container_kind("24 x 0,33 l (7,92 l)",
                                        parse_packs("24 x 0,33 l (7,92 l)").container_sizes), CAN)

    def test_pack_count_and_unit(self):
        pack = parse_packs("24 x 0,33 l.").packs[0]
        self.assertEqual((pack.count, pack.unit_l), (24, 0.33))


class StatedPriceTest(unittest.TestCase):
    def test_forms(self):
        cases = {
            "Pr. liter 8,00": 8.0,
            "Literpris 9,47 + pant.": 9.47,
            "Pr ltr 10,10": 10.10,
            "Kasse med 24 stk. 84.00/10.61 pr. liter": 10.61,
            "1 l = 5,33 DKK | 0,71 €": 5.33,
            "Liter = kr. 8,33": 8.33,
        }
        for text, want in cases.items():
            self.assertEqual(parse_stated_kr_per_l(text), want, text)

    def test_max_bound_is_not_a_stated_price(self):
        self.assertIsNone(parse_stated_kr_per_l("Ekskl. embl. Pr. liter max. 12.63"))

    def test_none(self):
        self.assertIsNone(parse_stated_kr_per_l("24 x 33 CL"))


class PantTest(unittest.TestCase):
    def test_status(self):
        self.assertEqual(pant_status("Literpris 8,00 + pant."), "excl")
        self.assertEqual(pant_status("33 cl. Ex. pant"), "excl")
        self.assertEqual(pant_status("Excl pant"), "excl")
        self.assertEqual(pant_status("Ekskl. embl."), "excl")
        self.assertEqual(pant_status("Ingen pant."), "excl")
        self.assertEqual(pant_status("24 x 33 cl inkl. pant"), "incl")
        self.assertEqual(pant_status("Pris inkl. pant"), "incl")
        self.assertEqual(pant_status("24 x 33 CL"), "unstated")

    def test_rates(self):
        # Cans only; the can rate matches REMA's deposit field for a 33 cl can (1.00).
        self.assertEqual(pant_per_container(0.33, CAN), 1.0)
        self.assertIsNone(pant_per_container(0.5, BOTTLE))


class ContainerTest(unittest.TestCase):
    def test_can_words(self):
        self.assertEqual(container_kind("24 x 33 cl. ds.", [0.33]), CAN)
        self.assertEqual(container_kind("33 cl/24 ds", [0.33]), CAN)
        self.assertEqual(container_kind("Pepsi Max dåser 6 x 33 cl", [0.33]), CAN)

    def test_bottle_words_and_sizes(self):
        self.assertEqual(container_kind("Pepsi Max PET 24 x 0,33 l.", [0.33]), BOTTLE)
        self.assertEqual(container_kind("150 cl. 1 flaske", [1.5]), BOTTLE)
        self.assertEqual(container_kind("Pr. fl. 8,92", [0.5]), BOTTLE)
        self.assertEqual(container_kind("2 liter", [2.0]), BOTTLE)  # no cans of 1 L or more

    def test_rema_deposit_150_is_pet(self):
        self.assertEqual(container_kind("PEPSI MAX 50 CL.", [0.5], deposit_per_unit=1.5), BOTTLE)

    def test_under_one_litre_without_bottle_word_is_a_can(self):
        self.assertEqual(container_kind("24 x 33 cl", [0.33]), CAN)
        self.assertEqual(container_kind("PEPSI MAX 33 CL.", [0.33], deposit_per_unit=1.0), CAN)
        self.assertEqual(container_kind("PEPSI MAX 1.98 LTR. / 6 PK.", [0.33],
                                        deposit_per_unit=1.0), CAN)

    def test_unknown(self):
        self.assertIsNone(container_kind("27,5 cl. fl. 33 cl. ds.", [0.275, 0.33]))
        self.assertIsNone(container_kind("Dåser eller glas, 33 cl", [0.33]))
        self.assertIsNone(container_kind("Frit valg", []))


class DateTest(unittest.TestCase):
    def test_tjek_utc_evening_is_next_danish_day(self):
        self.assertEqual(copenhagen_date("2026-10-22T22:00:00+0000"), date(2026, 10, 23))
        self.assertEqual(copenhagen_date("2026-10-29T22:59:59+0000"), date(2026, 10, 29))
        self.assertEqual(copenhagen_date("2026-09-17T00:00:00+00:00"), date(2026, 9, 17))

    def test_bad_timestamp_raises(self):
        for bad in (None, "", "not a date", "2026-13-01T00:00:00+0000"):
            with self.assertRaises(ValueError):
                copenhagen_date(bad)

    def test_fixed_rule_fallback(self):
        utc = timezone.utc
        self.assertEqual(fixed_rule_offset_hours(datetime(2026, 10, 22, 22, tzinfo=utc)), 2)
        # Summer time ends 2026-10-25 01:00 UTC and starts 2026-03-29 01:00 UTC.
        self.assertEqual(fixed_rule_offset_hours(datetime(2026, 10, 25, 0, 59, tzinfo=utc)), 2)
        self.assertEqual(fixed_rule_offset_hours(datetime(2026, 10, 25, 1, 0, tzinfo=utc)), 1)
        self.assertEqual(fixed_rule_offset_hours(datetime(2026, 3, 29, 0, 59, tzinfo=utc)), 1)
        self.assertEqual(fixed_rule_offset_hours(datetime(2026, 3, 29, 1, 0, tzinfo=utc)), 2)


class ResolveVolumeTest(unittest.TestCase):
    def test_text_and_fields_agree(self):
        self.assertEqual(resolve_volume(75, [7.92], 7.92, None), (7.92, None))

    def test_stated_price_settles_mismatch(self):
        # REMA flyer row: price is per can, text also mentions the 24-can case.
        self.assertEqual(resolve_volume(3.5, [0.33], 0.33, 10.61), (0.33, None))
        vol, reason = resolve_volume(79.99, [7.92], 7.92, 10.10)
        self.assertEqual(vol, 7.92)

    def test_mismatch_without_stated_price_quarantined(self):
        vol, reason = resolve_volume(75, [7.92], 0.33, None)
        self.assertIsNone(vol)
        self.assertIn("quantity fields", reason)

    def test_stated_price_contradicts_quarantined(self):
        vol, reason = resolve_volume(75, [7.92], 7.92, 4.0)
        self.assertIsNone(vol)

    def test_several_text_sizes_quarantined(self):
        vol, reason = resolve_volume(75, [5.94, 7.92], 7.92, None)
        self.assertIsNone(vol)
        self.assertIn("several", reason)

    def test_fields_only_quarantined(self):
        vol, reason = resolve_volume(64.95, [], 7.92, None)
        self.assertIsNone(vol)

    def test_zero_size_is_not_a_volume(self):
        self.assertEqual(parse_packs("0 cl").packs, [])
        self.assertEqual(parse_packs("0 x 33 cl").packs, [])
        self.assertEqual(resolve_volume(10, [], 0.0, 5.0), (None, "no pack size found"))

    def test_text_only_accepted(self):
        self.assertEqual(resolve_volume(12, [1.5], None, None), (1.5, None))


if __name__ == "__main__":
    unittest.main()
