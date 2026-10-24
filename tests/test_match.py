import unittest

from dealfinder.match import (CULT, KEEP, PEPSI_MAX, QUARANTINE, REJECT, VARIANTS,
                              classify_product, is_danish_dealer)


class ProductMatchTest(unittest.TestCase):
    def assertKeep(self, text, product, variant=None):
        status, got, reason = classify_product(text, variant)
        self.assertEqual((status, got), (KEEP, product), reason)

    def assertStatus(self, text, status, variant=None):
        got, _, reason = classify_product(text, variant)
        self.assertEqual(got, status, reason)

    def test_plain_pepsi_max_kept(self):
        self.assertKeep("PEPSI MAX 1.5 LTR.", PEPSI_MAX)
        self.assertKeep("Pepsi Max Pet 24 x 33 CL", PEPSI_MAX)
        self.assertKeep("PEPSI MAX 1.98 LTR. / 6 PK.", PEPSI_MAX, variant="6 PK.")

    def test_mixed_rows_count_as_pepsi_max(self):
        self.assertKeep("Pepsi Max eller Faxe Kondi 33 cl. Ex. pant", PEPSI_MAX)
        self.assertKeep("Faxe Kondi eller Pepsi Max sodavand 2 liter. + pant.", PEPSI_MAX)
        self.assertKeep("Pepsi Max el. Faxe Kondi sodavand 33 cl/24 ds", PEPSI_MAX)
        self.assertKeep("FAXE KONDI | PEPSI MAX Original | 0 kalorier", PEPSI_MAX)

    def test_max_flavours_rejected(self):
        for text in ("Pepsi Max Lime 1,5 l", "Pepsi Max Cherry 33 cl", "PEPSI MAX MANGO",
                     "Pepsi Max Raspberry 24 x 33 cl", "Pepsi Max Kirsebær"):
            self.assertStatus(text, REJECT)

    def test_flavour_in_rema_variant_rejected(self):
        self.assertStatus("PEPSI MAX 1.5 LTR. / LIME", REJECT, variant="LIME")

    def test_regular_pepsi_rejected(self):
        self.assertStatus("Pepsi, Mirinda el. Mountain Dew 24 x 0,33 l.", REJECT)

    def test_pepsi_several_variants_without_max_listed_as_variants(self):
        # Ruling pepsi-flere-varianter-rows-listed-probably-max-not-in-history.
        status, product, reason = classify_product("Pepsi eller Faxe Kondi Flere varianter. 24 x 33 cl ds")
        self.assertEqual((status, product), (VARIANTS, PEPSI_MAX))
        self.assertEqual(reason, "variants, Max likely")
        self.assertStatus("PEPSI Frit valg 24 x 33 cl ds", VARIANTS)

    def test_flavour_anywhere_rejected(self):
        self.assertStatus("Pepsi Max med lime 24 x 33 cl ds", REJECT)
        self.assertStatus("Pepsi Max Ananas 33 cl ds", REJECT)
        self.assertStatus("Pepsi Max eller Faxe Kondi\nFlere varianter. Fx lime.", REJECT)

    def test_unexplained_words_after_max_quarantined(self):
        self.assertStatus("Pepsi Max Xtreme Edition 33 cl ds", QUARANTINE)
        self.assertStatus("Pepsi Max med smag 33 cl ds", QUARANTINE)

    def test_plain_rows_from_fixtures_stay_kept(self):
        for text in ("Pepsi Max Pet\n24 x 33 CL\nB:2122708",
                     "PEPSI MAX\nGRÆNSENS BILLIGSTE!\nPET\n6 x 1,5 l (9 l)",
                     "Pepsi Max PET\n24 x 0,33 l. | Pr. ks. | Spar 34% ift. DK*",
                     "Faxe Kondi eller Pepsi Max*\n24 x 33 cl. Literpris 9,47 + pant.",
                     "Pepsi Max, Faxe Kondi, Royal øl, Anarkist el. Booster\nUdvalgte varianter",
                     "Øl- eller sodavandsmarked\n18x33 cl. ds. Royal Export. 24x33 cl. ds. Pepsi Max eller Faxe Kondi. Gælder kun lukkede forpakninger.",
                     "PEPSI / PEPSI MAX\nFlere varianter\n24 x 0,33 l",
                     "Pepsi Max 1,5 l", "Pepsi Max sodavand 2 liter", "Pepsi Max Zero Sugar 33 cl"):
            self.assertKeep(text, PEPSI_MAX)

    def test_syrup_rejected(self):
        self.assertStatus("Sodastream sirup Pepsi Max Flaske à 440 ml", REJECT)

    def test_cult_energy_kept(self):
        self.assertKeep("CULT Energy Original eller Sugar Free Kasse à 12 x 0,5 liter", CULT)
        self.assertKeep("Cult Energy Raw 50 cl", CULT)

    def test_cultura_rejected(self):
        self.assertStatus("A38 NATUREL 0,4% 1 KG. / ARLA CULTURA, ØKOLOGISK", REJECT)
        self.assertStatus("KEFIR NATUREL 1 LTR. / ARLA CULTURA, LAKTOSEFRI", REJECT)

    def test_cult_shaker_and_non_drinks_rejected(self):
        self.assertStatus("CULT SHAKER Lemon + Lime el. Astronaut 6 x 0,33 l", REJECT)
        self.assertStatus("Shaker eller Royal Club 27,5-33 cl.", REJECT)
        self.assertStatus("CULT Gulvflise Italiensk gulvflise 60×60 cm", REJECT)

    def test_cult_without_energy_quarantined(self):
        self.assertStatus("Cult Mofo 6 x 0,25 l", QUARANTINE)

    def test_unrelated_rejected(self):
        self.assertStatus("KIRSEBÆRSAUCE 530 GR.", REJECT)


class DanishDealerTest(unittest.TestCase):
    def test_danish_chains_kept(self):
        for name in ("Netto", "føtex", "Bilka", "REMA 1000", "MENY", "SPAR", "Løvbjerg",
                     "365discount", "SuperBrugsen", "Kvickly", "Lidl", "nemlig.com"):
            self.assertTrue(is_danish_dealer(name, "DK"), name)

    def test_border_shops_excluded_even_with_country_dk(self):
        # Tjek reports country DK for these, so the country field cannot decide.
        for name in ("BorderShop", "Poetzsch Padborg", "fakta Tyskland", "Nielsen Scan-Shop",
                     "Calle", "Fleggaard", "XL-BYG"):
            self.assertFalse(is_danish_dealer(name, "DK"), name)

    def test_non_dk_country_excluded(self):
        self.assertFalse(is_danish_dealer("Netto", "DE"))
        self.assertFalse(is_danish_dealer("Netto", "SE"))


if __name__ == "__main__":
    unittest.main()
