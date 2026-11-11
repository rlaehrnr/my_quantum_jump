import unittest

import pandas as pd


class ResidualBacktestTests(unittest.TestCase):
    def test_benchmark_uses_prior_month_close_and_preserves_missing_months(self):
        from utils.ui_usa_residual import _sp500_monthly_returns, _summary

        months = pd.Index(["2025-02", "2025-03"])
        prices = pd.DataFrame(
            {"Close": [100, 95, 90, 108, 112]},
            index=pd.to_datetime(["2025-01-31", "2025-02-10", "2025-02-28", "2025-03-31", "2025-04-30"]),
        )
        returns = _sp500_monthly_returns(prices, months)
        self.assertAlmostEqual(returns.loc["2025-02"], -0.10)
        self.assertAlmostEqual(returns.loc["2025-03"], 0.20)

        strategy = pd.DataFrame({"기존 전략": [0.0, 0.0]}, index=months)
        benchmark = _summary(strategy, strategy, returns).set_index("전략").loc["S&P 500 (가격 지수)"]
        self.assertAlmostEqual(benchmark["비용 전 CAGR"], 1.08 ** 6 - 1)
        self.assertAlmostEqual(benchmark["비용 전 MDD"], -0.10)
        self.assertTrue(pd.isna(benchmark["비용 후 CAGR"]))

        incomplete = _sp500_monthly_returns(prices.drop(pd.Timestamp("2025-03-31")), months)
        benchmark = _summary(strategy, strategy, incomplete).set_index("전략").loc["S&P 500 (가격 지수)"]
        self.assertTrue(pd.isna(benchmark["비용 전 CAGR"]))
        self.assertTrue(pd.isna(benchmark["비용 전 MDD"]))

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

    def test_equal_weight_counts_overlapping_tickers_once(self):
        from utils.us_residual_backtest import run_residual_backtest

        month = "2026-01"
        stocks = pd.DataFrame({
            "투자월": [month] * 3,
            "종목코드": ["A", "B", "C"],
            "시가총액": [300, 200, 100],
            "이번달수익률": [30, 0, 0],
            "1개월(%)": [0, 0, 0],
            "3개월(%)": [20, 10, 5],
            "6개월(%)": [20, 10, 5],
            "12개월(%)": [20, 10, 5],
        })
        scores = pd.DataFrame({
            "month": [month] * 3, "ticker": ["A", "B", "C"], "score": [3, 2, 1],
        })
        results = run_residual_backtest(
            stocks, scores, pd.Series([True], index=[month]),
            universe=500, cutoff=3, original_ranks=(1, 1), residual_ranks=(1, 3), fee=0,
        )

        self.assertAlmostEqual(results["gross"].loc[month, "기존 50% + 잔차 50%"], 0.20)
        self.assertAlmostEqual(results["gross"].loc[month, "종목 균등 배분"], 0.10)


if __name__ == "__main__":
    unittest.main()
