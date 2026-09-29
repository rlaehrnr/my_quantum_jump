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
        self.assertEqual(result.loc[0, "회복기간"], "2.0개월")

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
