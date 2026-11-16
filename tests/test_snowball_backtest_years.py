import unittest

import pandas as pd

from utils.snowball import filter_backtest_years


class BacktestYearFilterTest(unittest.TestCase):
    def setUp(self):
        self.backtest = pd.DataFrame(
            {
                "hold_month": ["2023-12", "2024-01", "2024-02", "2025-01"],
                "ret_strategy": [0.5, -0.1, 0.2, 0.1],
                "ret_QQQ": [0.3, float("nan"), 0.15, -0.04],
                "cost": [0.0025, 0.001, 0.0, 0.0],
                "cum_strategy": [1.5, 1.35, 1.62, 1.782],
                "dd_strategy": [0.0, -0.1, 0.0, 0.0],
                "cum_QQQ": [1.3, 1.3, 1.495, 1.4352],
            }
        )

    def test_selected_year_compounds_from_one_with_actual_monthly_costs(self):
        selected = filter_backtest_years(self.backtest, 2024, 2024)
        self.assertEqual(selected["hold_month"].tolist(), ["2024-01", "2024-02"])
        self.assertEqual(selected["cost"].tolist(), [0.001, 0.0])
        self.assertEqual(selected["ret_strategy"].tolist(), [-0.1, 0.2])
        self.assertAlmostEqual(selected["cum_strategy"].iloc[0], 0.9)
        self.assertAlmostEqual(selected["cum_strategy"].iloc[-1], 1.08)
        self.assertAlmostEqual(selected["dd_strategy"].iloc[0], -0.1)
        self.assertEqual(selected["cum_QQQ"].tolist(), [1.0, 1.15])
        self.assertEqual(self.backtest["cum_strategy"].iloc[1], 1.35)

    def test_full_span_preserves_all_report_values(self):
        pd.testing.assert_frame_equal(
            filter_backtest_years(self.backtest, 2023, 2025), self.backtest
        )
