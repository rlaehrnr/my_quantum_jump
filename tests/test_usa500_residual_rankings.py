import unittest

import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest


class ResidualRankingTests(unittest.TestCase):
    def test_score_uses_exactly_the_previous_36_months_ending_two_months_back(self):
        from utils.us_residual_backtest import calculate_residual_scores

        month = pd.Period("2026-11", freq="M")
        periods = pd.period_range(end=month, periods=38, freq="M")
        rng = np.random.default_rng(847)
        factors = pd.DataFrame(rng.normal(0, 0.02, (38, 4)), index=periods)
        noise = rng.normal(0, 0.05, 38)
        returns = pd.DataFrame({
            "A": factors.iloc[:, 0] * 2 + factors.iloc[:, 3] + noise,
            "B": np.nan,
            "C": np.nan,
        }, index=periods)
        supplemental = returns.copy()
        supplemental["B"] = returns["A"]
        returns.iloc[:12, 1] = supplemental.iloc[:12, 1]

        scores = calculate_residual_scores(month, returns, supplemental, factors)
        x = np.column_stack([np.ones(36), factors.iloc[:36, :3]])
        excess = returns.iloc[:36, 0] - factors.iloc[:36, 3]
        residual = excess - x @ np.linalg.lstsq(x, excess, rcond=None)[0]
        expected = residual.iloc[-11:].mean() / residual.iloc[-11:].std()
        self.assertEqual(scores.index.tolist(), ["A", "B"])
        np.testing.assert_allclose(scores.values, [expected, expected], rtol=1e-12)
        returns.iloc[-2:] = 200
        factors.iloc[-2:] = -200
        pd.testing.assert_series_equal(scores, calculate_residual_scores(month, returns, supplemental, factors))
        self.assertTrue(calculate_residual_scores(month, returns, supplemental, factors.iloc[:35]).empty)

    def test_missing_returns_do_not_change_rank_or_become_zero(self):
        from utils.ui_usa_residual import _ranking_table

        candidates = pd.DataFrame({
            "종목코드": list("ABCDEFGHIJKL"),
            "시가총액": range(100, 88, -1),
            "이번달수익률": 99.0,
        })
        scores = pd.Series(range(12, 0, -1), index=candidates["종목코드"])
        returns = pd.Series([0.0, 10.0, np.nan], index=["A", "B", "C"])
        ranked = _ranking_table(candidates, scores, returns)
        self.assertEqual(ranked["종목코드"].tolist(), list("ABCDEFGHIJ"))
        self.assertEqual(ranked["순위"].tolist(), list(range(1, 11)))
        self.assertEqual(ranked.loc[0, "이번달수익률"], 0)
        self.assertEqual(ranked.loc[1, "이번달수익률"], 10)
        self.assertTrue(ranked.loc[2:, "이번달수익률"].isna().all())

    def test_rank_slider_updates_average_including_zero_returns(self):
        app = AppTest.from_string("""
import pandas as pd
from utils.ui_usa_residual import _render_ranking_table
rows = pd.DataFrame({
    "순위": [1, 2, 3], "종목코드": ["A", "B", "C"],
    "통합티커_L": ["https://example.com/#A", "https://example.com/#B", "https://example.com/#C"],
    "종목명_L": ["https://example.com/#A", "https://example.com/#B", "https://example.com/#C"],
    "잔차 점수": [3.0, 2.0, 1.0], "이번달수익률": [0.0, 4.0, float("nan")],
})
_render_ranking_table(rows, key="test_residual_ranks")
""").run()
        self.assertFalse(app.exception)
        self.assertTrue(any("+2.00%" in item.value for item in app.markdown))
        app.slider(key="test_residual_ranks").set_value((1, 1)).run()
        self.assertFalse(app.exception)
        self.assertTrue(any("0.00%" in item.value for item in app.markdown))
        app.slider(key="test_residual_ranks").set_value((3, 3)).run()
        self.assertTrue(any("수익률 자료 없음" in item.value for item in app.markdown))
