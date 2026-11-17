import unittest

import pandas as pd

from utils.static_allocation import default_rows
from utils.static_allocation_history import calculate_history, target_weights


class StaticAllocationHistoryTest(unittest.TestCase):
    def test_start_of_month_weights_drift_and_season_changes(self):
        sessions = pd.to_datetime([
            "2026-04-30", "2026-05-04", "2026-05-05", "2026-05-29",
            "2026-06-01", "2026-06-30",
        ])
        prices = pd.DataFrame({"A": [100, 110, 121, 121, 121, 121]}, index=sessions)
        results = calculate_history(
            prices, sessions, winter={"A": 1.0}, summer={"A": 0.5},
            current_month=pd.Period("2026-06", freq="M"),
        )
        # Half the starting capital holds the ETF, so the 21% ETF gain produces 10.5%.
        self.assertAlmostEqual(results.monthly.iloc[0], 0.105)
        self.assertAlmostEqual(results.daily["포트 누적"].iloc[-1], 0)
        self.assertAlmostEqual(results.equity.iloc[-1], 1.105)
        self.assertEqual(results.monthly.index.tolist(), [pd.Period("2026-05", freq="M")])

    def test_daily_returns_are_computed_from_drifted_value(self):
        sessions = pd.to_datetime(["2026-10-30", "2026-11-02", "2026-11-03"])
        prices = pd.DataFrame({"A": [100, 110, 121]}, index=sessions)
        result = calculate_history(
            prices, sessions, winter={"A": 0.5}, summer={},
            current_month=pd.Period("2026-11", freq="M"),
        )
        self.assertAlmostEqual(result.daily.iloc[-1]["포트 일간"], 1.105 / 1.05 - 1)
        self.assertAlmostEqual(result.daily.iloc[-1]["포트 누적"], 0.105)
        self.assertTrue(result.monthly.empty)

    def test_missing_session_leaves_gap_and_truncates_current_month(self):
        sessions = pd.to_datetime([
            "2026-04-30", "2026-05-04", "2026-05-05", "2026-05-29",
            "2026-06-01", "2026-06-30",
            "2026-07-01", "2026-07-31",
            "2026-08-03", "2026-08-04", "2026-08-05",
        ])
        prices = pd.DataFrame({"A": [100, 105, 106, 110, None, 115, 120, 130, 140, None, 150]}, index=sessions)
        result = calculate_history(
            prices, sessions, winter={"A": 1.0}, summer={"A": 1.0},
            current_month=pd.Period("2026-08", freq="M"),
        )
        self.assertTrue(pd.isna(result.monthly.loc["2026-06"]))
        self.assertAlmostEqual(result.monthly.loc["2026-07"], 130 / 115 - 1)
        self.assertEqual(result.daily.index.tolist(), [pd.Timestamp("2026-08-03")])
        self.assertEqual(result.equity.index[0], pd.Timestamp("2026-06-30"))

    def test_missing_previous_close_excludes_initial_partial_month(self):
        sessions = pd.to_datetime(["2026-04-30", "2026-05-04", "2026-05-29", "2026-06-01", "2026-06-30"])
        prices = pd.DataFrame({"A": [None, 100, 120, 120, 132]}, index=sessions)
        result = calculate_history(
            prices, sessions, winter={}, summer={"A": 1.0},
            current_month=pd.Period("2026-07", freq="M"),
        )
        self.assertEqual(result.monthly.index.tolist(), [pd.Period("2026-06", freq="M")])
        self.assertAlmostEqual(result.monthly.iloc[0], 0.10)

    def test_grvt_and_cash_have_zero_return_with_weight_retained(self):
        weights = target_weights(default_rows("us_summer"), "us")
        self.assertAlmostEqual(sum(weights.values()), 0.60)
        self.assertNotIn("GRVT", weights)
        self.assertNotIn("", weights)
