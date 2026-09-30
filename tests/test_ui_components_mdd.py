import unittest

import pandas as pd

from utils.ui_components import get_mdd_history


class GetMddHistoryTests(unittest.TestCase):
    def test_drawdown_period_starts_on_first_declining_month(self):
        equity = pd.Series(
            [100.0, 90.0, 80.0, 105.0],
            index=["2018-05", "2018-06", "2018-07", "2018-08"],
        )

        result = get_mdd_history(equity)

        self.assertEqual(result.loc[0, "MDD"], "-20.00%")
        self.assertEqual(result.loc[0, "기간"], "2018-06 ~ 2018-07")
        self.assertEqual(result.loc[0, "회복기간"], "2개월")

    def test_recovery_period_counts_calendar_months_without_rounding(self):
        equity = pd.Series(
            [100.0, 90.0, 88.0, 86.0, 84.0, 82.0, 80.0, 105.0],
            index=[
                "2020-12",
                "2021-01",
                "2021-02",
                "2021-03",
                "2021-04",
                "2021-05",
                "2021-06",
                "2021-07",
            ],
        )

        result = get_mdd_history(equity)

        self.assertEqual(result.loc[0, "기간"], "2021-01 ~ 2021-06")
        self.assertEqual(result.loc[0, "회복기간"], "6개월")

    def test_recovery_within_same_calendar_month_is_zero_months(self):
        equity = pd.Series(
            [100.0, 90.0, 105.0],
            index=["2021-01", "2021-01", "2021-01"],
        )

        result = get_mdd_history(equity)

        self.assertEqual(result.loc[0, "회복기간"], "0개월")

    def test_ongoing_drawdown_period_starts_on_first_declining_month(self):
        equity = pd.Series(
            [100.0, 95.0, 90.0],
            index=["2026-07", "2026-08", "2026-09"],
        )

        result = get_mdd_history(equity)

        self.assertEqual(result.loc[0, "기간"], "2026-08 ~ 2026-09")
        self.assertEqual(result.loc[0, "회복기간"], "진행중")


if __name__ == "__main__":
    unittest.main()
