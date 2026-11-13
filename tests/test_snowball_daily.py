import unittest

import pandas as pd

from utils.snowball_daily import month_performance, preview_monthly, holding_weights, signal_for_month


class SnowballDailyTests(unittest.TestCase):
    def setUp(self):
        self.month = pd.Period("2026-11", "M")
        self.daily = pd.DataFrame(
            {"A": [100, 110, 110, 121], "B": [100, 90, 100, None]},
            index=pd.to_datetime(["2026-10-30", "2026-11-02", "2026-11-03", "2026-11-04"]),
        )

    def test_fixed_initial_weights_drift_and_incomplete_date_is_omitted(self):
        performance = month_performance(self.daily, {"A": .5, "B": .5}, self.month)
        self.assertEqual(["2026-11-02", "2026-11-03"], list(performance.index.strftime("%Y-%m-%d")))
        self.assertAlmostEqual(performance.iloc[0]["포트 누적"], 0)
        self.assertAlmostEqual(performance.iloc[1]["포트 누적"], .05)
        self.assertAlmostEqual(performance.iloc[1]["포트 일간"], .05)
        self.assertAlmostEqual(performance.iloc[1]["A 누적"], .10)

    def test_missing_anchor_does_not_become_zero_return(self):
        performance = month_performance(self.daily.iloc[1:], {"A": 1}, self.month)
        self.assertTrue(performance.empty)

    def test_missing_internal_quote_keeps_daily_return_from_spanning_two_days(self):
        daily = self.daily.copy()
        daily.loc["2026-11-02", "B"] = None
        daily.loc["2026-11-04", "B"] = 105
        result = month_performance(daily, {"A": .5, "B": .5}, self.month)
        self.assertTrue(pd.isna(result.loc["2026-11-03", "포트 일간"]))
        self.assertAlmostEqual(result.loc["2026-11-04", "포트 누적"], .13)

    def test_preview_requires_every_candidate_on_latest_market_date(self):
        monthly = pd.DataFrame({"A": [50], "B": [100]},
                               index=pd.PeriodIndex(["2026-10"], freq="M"))
        self.assertIsNone(preview_monthly(monthly, self.daily, ["A", "B"], self.month))
        preview, date = preview_monthly(monthly, self.daily, ["A"], self.month)
        self.assertEqual(date, pd.Timestamp("2026-11-04"))
        self.assertAlmostEqual(preview.loc[self.month, "A"], 60.5)
        self.assertNotIn(self.month, monthly.index)

    def test_preview_requires_latest_completed_month(self):
        monthly = pd.DataFrame({"A": [50]}, index=pd.PeriodIndex(["2026-09"], freq="M"))
        self.assertIsNone(preview_monthly(monthly, self.daily, ["A"], self.month))

    def test_signal_lookup_handles_period_and_string_indexes(self):
        for key in (self.month, str(self.month)):
            signals = pd.DataFrame({"hold": ["A"]}, index=[key])
            self.assertEqual(signal_for_month(signals, self.month)["hold"], "A")
            self.assertEqual(signal_for_month(signals, self.month - 1), {})

    def test_weights_keep_strategy_weights_and_map_live_tickers(self):
        self.assertEqual(holding_weights({"holds": ["A", "B"]}), {"A": .5, "B": .5})
        self.assertEqual(holding_weights({"hold": "A"}), {"A": 1})
        self.assertEqual(holding_weights({"holds": {"A": .75, "B": .25}},
                                         {"A": "LIVE"}.get), {"LIVE": .75, "B": .25})


if __name__ == "__main__":
    unittest.main()
