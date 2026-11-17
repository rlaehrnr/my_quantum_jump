import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


PAGE = Path(__file__).resolve().parents[1] / "pages" / "8_정적자산배분.py"


class StaticAllocationPageTest(unittest.TestCase):
    def setUp(self):
        self.app = AppTest.from_file(str(PAGE)).run()
        self.assertFalse(self.app.exception)

    def edit(self, key, rows):
        self.app.session_state[key] = {
            "edited_rows": rows,
            "added_rows": [],
            "deleted_rows": [],
        }

    def results(self, market):
        return [
            item.value
            for item in self.app.dataframe
            if "목표 수량 (주)" in item.value
            and ("목표 금액 (USD)" in item.value) == (market == "us")
        ]

    def test_default_tabs_and_excel_weight_discrepancy(self):
        self.assertEqual({tab.label for tab in self.app.tabs}, {
            "한국", "11월–4월", "5월–10월", "미국",
        })
        self.assertIn("105%", self.app.warning[0].value)
        self.assertEqual(self.results("kr"), [])
        self.assertEqual(self.results("us"), [])

    def test_korean_seasons_preserve_distinct_weights_and_cash(self):
        self.app.number_input(key="kr_assets").set_value(1_000_000)
        self.edit("kr_winter", {0: {"가격 (원)": 50_000}})
        self.edit("kr_summer", {3: {"목표 비중 (%)": 3}, 0: {"가격 (원)": 50_000}})
        self.app.run()
        self.assertFalse(self.app.exception)
        self.assertFalse(self.app.warning)

        winter, summer = self.results("kr")
        self.assertEqual(winter.iloc[0]["목표 금액 (원)"], 150_000)
        self.assertEqual(winter.iloc[0]["목표 수량 (주)"], 3)
        self.assertEqual(summer.iloc[0]["목표 금액 (원)"], 100_000)
        self.assertEqual(summer.iloc[0]["목표 수량 (주)"], 2)
        self.assertEqual(summer.iloc[-1]["목표 금액 (원)"], 400_000)
        self.assertEqual(summer["목표 금액 (원)"].sum(), 1_000_000)
        self.assertTrue(summer["목표 수량 (주)"].isna().iloc[-1])

    def test_us_quantity_uses_usd_price_and_won_per_dollar(self):
        self.app.number_input(key="us_assets").set_value(2_000_000)
        self.app.number_input(key="us_allocation").set_value(50.0)
        self.edit("us_all_weather", {0: {"가격 (USD)": 20.0}})
        self.app.run()
        self.assertFalse(self.app.exception)
        result, = self.results("us")
        self.assertEqual(result.iloc[0]["목표 금액 (원)"], 100_000)
        self.assertTrue(result["목표 수량 (주)"].isna().all())

        # AppTest needs the data editor payload on each simulated rerun.
        self.edit("us_all_weather", {0: {"가격 (USD)": 20.0}})
        self.app.number_input(key="us_fx").set_value(1_250.0)
        self.app.run()
        self.assertFalse(self.app.exception)
        result, = self.results("us")
        self.assertEqual(result.iloc[0]["목표 금액 (USD)"], 80)
        self.assertEqual(result.iloc[0]["목표 수량 (주)"], 4)
        self.assertTrue(result["목표 수량 (주)"].isna().iloc[1])

    def test_invalid_korean_weights_block_results_after_funding(self):
        self.app.number_input(key="kr_assets").set_value(1_000_000)
        self.app.run()
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.results("kr")), 1)
        self.assertIn("105%", self.app.warning[0].value)
