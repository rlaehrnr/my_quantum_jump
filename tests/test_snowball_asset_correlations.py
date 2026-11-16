import pandas as pd
import unittest

from utils.snowball import monthly_asset_correlations


class AssetCorrelationTest(unittest.TestCase):
    def test_correlation_uses_only_overlapping_closed_months(self):
        months = pd.period_range("2024-01", periods=17, freq="M")
        increasing = [100.0]
        decreasing = [100.0]
        for i in range(1, len(months)):
            increasing.append(increasing[-1] * (1 + i / 100))
            decreasing.append(decreasing[-1] * (1 - i / 100))
        prices = pd.DataFrame({"A": increasing, "B": decreasing, "C": increasing}, index=months)
        prices.loc[[months[0], months[3]], "C"] = float("nan")
        prices.loc[months[-1], "B"] *= 20
        prices = prices.drop(months[2])

        corr = monthly_asset_correlations(prices, months[-1])

        self.assertAlmostEqual(corr.loc["A", "B"], -1)
        self.assertAlmostEqual(corr.loc["B", "A"], -1)
        self.assertAlmostEqual(corr.loc["A", "A"], 1)
        self.assertTrue(pd.isna(corr.loc["A", "C"]))
