import unittest
from unittest.mock import patch

import pandas as pd

from utils.momentum_daily import holding_performance, usa500_holding_weights


class MomentumDailyTests(unittest.TestCase):
    def setUp(self):
        self.month = pd.Period("2024-11", "M")
        self.dates = pd.to_datetime([
            "2024-10-29", "2024-10-30", "2024-11-02", "2024-11-03",
            "2024-11-04", "2024-12-01",
        ])
        self.sessions = pd.Series(1, index=self.dates[:5])

    @patch("utils.momentum_daily.load_holding_closes")
    def test_equal_weight_uses_previous_close_and_keeps_month_start_weights(self, load):
        load.return_value = pd.DataFrame(
            {"A": [90, 100, 110, 121, 133, 200], "B": [95, 100, 95, 100, None, 100]},
            index=self.dates,
        )
        actual = holding_performance("US", ("A", "B"), self.month)
        self.assertEqual(list(actual.index), list(self.dates[2:4]))
        self.assertAlmostEqual(actual.iloc[0]["포트 누적"], .025)
        self.assertAlmostEqual(actual.iloc[1]["포트 누적"], .105)
        self.assertAlmostEqual(actual.iloc[1]["포트 일간"], 1.105 / 1.025 - 1)

    @patch("utils.momentum_daily.load_holding_closes")
    def test_cash_uses_market_sessions_and_zero_returns(self, load):
        load.return_value = pd.DataFrame(index=self.sessions.index)
        actual = holding_performance("KR", ("CASH",), self.month)
        self.assertEqual(list(actual.index), list(self.dates[2:5]))
        self.assertTrue((actual == 0).all().all())

    @patch("utils.momentum_daily.load_holding_closes")
    def test_missing_month_end_close_does_not_create_an_estimate(self, load):
        load.return_value = pd.DataFrame(
            {"A": [100, None, 110, 121, 133], "B": 100}, index=self.dates[:5],
        )
        self.assertTrue(holding_performance("US", ("A", "B"), self.month).empty)

    @patch("utils.momentum_daily.load_holding_closes")
    def test_no_picks_skip_price_lookup(self, load):
        self.assertTrue(holding_performance("KR", (), self.month).empty)
        load.assert_not_called()

    def test_us_loader_requests_through_the_last_closed_session(self):
        from utils.momentum_daily import load_holding_closes

        start, end = self.dates[0], self.dates[3]
        closes = pd.DataFrame({"Close": 100}, index=self.dates[:5])
        load_holding_closes.clear()
        with patch("utils.momentum_daily.fdr.DataReader", return_value=closes) as read:
            result = load_holding_closes("US", ("BRK.B",), start, end)
        self.assertEqual(list(result.index), list(self.dates[:4]))
        self.assertEqual(set(result.columns), {"BRK.B"})
        self.assertEqual(
            {tuple(args) for args, _ in read.call_args_list},
            {("SPY", start, end + pd.Timedelta(days=1)),
             ("BRK-B", start, end + pd.Timedelta(days=1))},
        )


    @patch("utils.momentum_daily.load_holding_closes")
    def test_usa500_half_allocations_keep_rank_bounds_and_add_overlapping_weights(self, load):
        original = ["SKIP1", "SKIP2", "A", "B", "C", "D", "E", "F", "SKIP9"]
        residual = ["F", "G", "H", "I", "J", "K", "L", "M", "N", "SKIP10"]
        weights = usa500_holding_weights(original, residual, (3, 8), (1, 9))

        self.assertEqual(list(weights), list("ABCDEFGHIJKLMN"))
        self.assertAlmostEqual(sum(weights.values()), 1)
        self.assertAlmostEqual(weights["A"], .5 / 6)
        self.assertAlmostEqual(weights["N"], .5 / 9)
        self.assertAlmostEqual(weights["F"], .5 / 6 + .5 / 9)

        prices = pd.DataFrame(100.0, index=self.dates[:4], columns=list(weights))
        prices.loc[self.dates[2], ["A", "F", "N"]] = [112, 136, 118]
        load.return_value = prices
        actual = holding_performance("US", weights, self.month, weights=weights)
        self.assertAlmostEqual(actual.iloc[0]["포트 누적"], .07)
        self.assertAlmostEqual(actual.iloc[1]["포트 일간"], 1 / 1.07 - 1)

    def test_usa500_does_not_replace_an_incomplete_limb_with_the_other_limb(self):
        original = list("ABCDEFGH")
        self.assertEqual(usa500_holding_weights(original, list("JKLMNOPQ"), (3, 8), (1, 9)), {})
        self.assertEqual(usa500_holding_weights(original[:-1], list("JKLMNOPQR"), (3, 8), (1, 9)), {})
