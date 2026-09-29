import unittest
from unittest.mock import patch

import pandas as pd

from utils import calculator


class GoldDefenseTests(unittest.TestCase):
    def test_gold_below_six_month_average_uses_cash(self):
        allocate = getattr(calculator, "get_gold_defense_allocation", lambda *_: None)

        self.assertEqual(allocate(95.0, 100.0), "현금 100")

    def test_gold_at_or_above_six_month_average_uses_gold(self):
        allocate = getattr(calculator, "get_gold_defense_allocation", lambda *_: None)

        self.assertEqual(allocate(100.0, 100.0), "금 100")
        self.assertEqual(allocate(105.0, 100.0), "금 100")

    @patch("utils.calculator.get_gold_ma_all", return_value=(95.0, {6: 100.0, 12: 90.0}))
    @patch("utils.calculator.get_kospi_ma_all", return_value=(90.0, {6: 100.0}))
    def test_monthly_market_status_uses_six_month_gold_rule(self, _kospi, _gold):
        monthly = pd.DataFrame(
            {
                "종목선정일": ["2026-05-29"] * 200,
                "1개월(%)": [-1.0] * 200,
                "3개월(%)": [-1.0] * 200,
                "6개월(%)": [1.0] * 200,
                "12개월(%)": [1.0] * 200,
            }
        )

        status = calculator.get_korea_market_status(monthly)

        self.assertEqual(status["defense_alloc"], "현금 100")
        self.assertEqual(status["status"], "🛑 투자 중지 (현금 100)")

    def test_gold_price_link_opens_naver_chart(self):
        make_link = getattr(calculator, "get_gold_chart_link", lambda *_: None)

        self.assertEqual(
            make_link("185,576"),
            "https://m.stock.naver.com/fchart/marketindex/metals/M04020000#185,576",
        )

    @patch("utils.calculator.get_kospi_timing_for_backtest", return_value={})
    @patch(
        "utils.calculator.get_gold_timing_for_backtest",
        side_effect=lambda months: {"2026-01": months == 6},
    )
    def test_backtest_default_uses_six_month_gold_rule(self, _gold_timing, _kospi_timing):
        rows = 200
        monthly = pd.DataFrame(
            {
                "투자월": ["2026-01"] * rows,
                "종목코드": [f"{code:06d}" for code in range(rows)],
                "시가총액": list(range(rows, 0, -1)),
                "1개월(%)": [-1.0] * rows,
                "3개월(%)": [-1.0] * rows,
                "6개월(%)": [1.0] * rows,
                "12개월(%)": [1.0] * rows,
                "다음달수익률(%)": [1.0] * rows,
            }
        )

        result, _, _ = calculator.run_backtest_k200(
            monthly,
            2026,
            2026,
            6,
            True,
            (1, 6),
            (1, 2),
            30,
            30,
            gold_returns={"2026-01": 5.0},
            use_gold=True,
            use_gold_ma=True,
        )

        self.assertEqual(result.loc[0, "앙상블 (50:50 전략)"], 0.0)


if __name__ == "__main__":
    unittest.main()
