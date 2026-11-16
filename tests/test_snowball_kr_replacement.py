import unittest

import pandas as pd

from update_snowball_kr import ALL_TICKERS, required_monthly_bars
from utils import snowball


class SnowballKrReplacementTest(unittest.TestCase):
    def test_ddo_pension_uses_replacement_etfs_in_their_respective_baskets(self):
        self.assertIn("283580", snowball.MAMTAX_OFFENSE)
        self.assertNotIn("192090", snowball.MAMTAX_OFFENSE)
        self.assertIn("0189B0", snowball.MAMTAX_DEFENSE)
        self.assertNotIn("144600", snowball.MAMTAX_DEFENSE)
        self.assertIn("283580", ALL_TICKERS)
        self.assertIn("0189B0", ALL_TICKERS)

    def test_ddo_pension_adds_energy_to_offense_and_copper_to_defense(self):
        self.assertIn("218420", snowball.MAMTAX_OFFENSE)
        self.assertNotIn("218420", snowball.MAMTAX_DEFENSE)
        self.assertIn("160580", snowball.MAMTAX_DEFENSE)
        self.assertNotIn("160580", snowball.MAMTAX_OFFENSE)
        self.assertIn("218420", ALL_TICKERS)
        self.assertIn("160580", ALL_TICKERS)

    def test_recent_silver_listing_can_be_collected_while_other_thresholds_stay_the_same(self):
        october = pd.Period("2026-10")
        self.assertEqual(required_monthly_bars("0189B0", october), 7)
        self.assertEqual(required_monthly_bars("283580", october), 13)
        self.assertEqual(required_monthly_bars("0189B0", pd.Period("2027-06")), 13)
