import unittest

import pandas as pd


class ResidualBacktestTests(unittest.TestCase):
    def test_rank_selection_shared_defense_and_trade_costs(self):
        from utils.us_residual_backtest import run_residual_backtest

        months = ["2026-01", "2026-02"]
        stocks = pd.DataFrame(
            [
                {"투자월": month, "종목코드": ticker, "시가총액": cap, "이번달수익률": ret,
                 "1개월(%)": 0, "3개월(%)": mom, "6개월(%)": mom, "12개월(%)": mom}
                for month in months
                for ticker, cap, mom, ret in [("A", 200, 15, 20), ("B", 100, 5, 0)]
            ]
        )
        scores = pd.DataFrame({"month": months * 2, "ticker": ["A", "A", "B", "B"],
                               "score": [2, 2, 1, 1]})
        results = run_residual_backtest(
            stocks, scores, pd.Series([True, False], index=months),
            universe=500, cutoff=2, original_ranks=(1, 1), residual_ranks=(2, 2), fee=0.0025,
        )
        self.assertAlmostEqual(results["gross"].loc[months[0], "기존 50% + 잔차 50%"], 0.10)
        self.assertAlmostEqual(results["net"].loc[months[0], "기존 50% + 잔차 50%"], 0.09725)
        self.assertAlmostEqual(results["gross"].loc[months[1], "기존 50% + 잔차 50%"], 0)
        self.assertAlmostEqual(results["net"].loc[months[1], "기존 50% + 잔차 50%"], -0.0025)


if __name__ == "__main__":
    unittest.main()
