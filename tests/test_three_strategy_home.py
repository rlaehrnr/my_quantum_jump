import unittest
from unittest.mock import Mock, patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from utils import momentum_daily, three_strategy_live as live, three_strategy_store as store, three_strategy_view as view
from utils.three_strategy import LEGS, SNOW


class ThreeStrategyHomeTests(unittest.TestCase):
    def test_daily_mix_uses_common_closes_and_previous_displayed_close(self):
        dates = pd.to_datetime(["2026-11-02", "2026-11-03", "2026-11-04"])
        curves = {
            "kospi": pd.Series([.10, .20, .30], index=dates),
            "small": pd.Series([.05, .15], index=dates[[0, 2]]),
        }
        result = live.combine_daily(curves, {"kospi": 3, "snowball": 0, "small": 1})
        self.assertEqual(result.index.tolist(), dates[[0, 2]].tolist())
        self.assertAlmostEqual(result["포트 일간"].iloc[1], 1.2625 / 1.0875 - 1)
        self.assertTrue(live.combine_daily(curves, {"kospi": 3, "snowball": 1}).empty)

    def test_smallcap_uses_equal_weights_for_unique_codes_from_code_only_sheets(self):
        rows = {
            "ddo": [["종목명", "종목코드"], ["예시 우선주", "00104K"], ["예시 보통주", "000002"]],
            "sso": [["종목명", "종목코드"], ["예시 우선주", "00104K"]],
            "mom": [],
        }
        sheet = Mock()
        sheet.worksheet.side_effect = lambda tab: Mock(get_all_values=lambda: rows[tab])
        closes = pd.DataFrame({"00104K": [100, 110, 99], "000002": [300, 300, 330]},
                              index=pd.to_datetime(["2025-10-31", "2025-11-03", "2025-11-04"]))
        store.smallcap_positions.clear()
        self.addCleanup(store.smallcap_positions.clear)
        with (
            patch.object(store, "portfolio_sheet", return_value=sheet),
            patch.object(momentum_daily, "load_holding_closes", return_value=closes),
        ):
            current = live.smallcap_current(pd.Period("2025-11"))
        self.assertEqual(current.holdings["종목코드"].unique().tolist(), ["00104K", "000002"])
        self.assertAlmostEqual(current.performance["포트 누적"].iloc[0], .05)
        self.assertAlmostEqual(current.performance["포트 일간"].iloc[1], 1.045 / 1.05 - 1)

    def test_unread_smallcap_account_keeps_other_holdings_but_blocks_return(self):
        positions = pd.DataFrame([{"계좌": "또", "종목명": "예시", "종목코드": "00104K", "수량": 2}])
        with patch.object(live, "smallcap_positions", return_value=(positions, ["쏘"])):
            current = live.smallcap_current(pd.Period("2026-11"))
        self.assertEqual(current.holdings["종목코드"].tolist(), ["00104K"])
        self.assertTrue(current.performance.empty)
        self.assertIn("쏘", current.note)

    def test_usd_curve_uses_daily_fx_and_ignores_a_missing_quote(self):
        dates = pd.to_datetime(["2026-10-30", "2026-11-02", "2026-11-03"])
        curve = pd.Series([.1, .2], index=dates[1:])
        fx = pd.Series([1000, 1200], index=dates[[0, 2]])
        converted = live.usd_curve_to_krw(curve, fx, dates[0])
        self.assertEqual(converted.index.tolist(), [dates[2]])
        self.assertAlmostEqual(converted.iloc[0], .44)

    def test_default_page_and_strategy_tabs_render_without_sheet_access(self):
        with (
            patch.object(live, "kospi_records", return_value=pd.DataFrame()),
            patch.object(live, "snowball_inputs", return_value={}),
            patch.object(live, "smallcap_positions", side_effect=OSError),
            patch.object(view, "load_history", side_effect=OSError),
        ):
            app = AppTest.from_file("app.py", default_timeout=30).run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.title[0].value, "🧩 3전략 조합")
        self.assertEqual([tab.label for tab in app.tabs], ["3전략 조합", "코스피", "스노우볼", "소형주"])
        self.assertEqual([header.value for header in app.tabs[0].get("subheader")][-2:],
                         ["📈 백테스트 성과", "현재 투자비율"])
        self.assertEqual(len(app.tabs[0].get("number_input")), 7)
        self.assertFalse(app.get("popover"))

    def test_returning_to_smallcap_only_loads_the_smallcap_panel(self):
        current = live.CurrentHoldings(pd.DataFrame([{"종목명": "예시"}]), pd.DataFrame())
        with (
            patch.object(live, "smallcap_current", return_value=current),
            patch.object(live, "kospi_current") as kospi,
            patch.object(live, "snowball_current") as snowball,
            patch.object(view, "load_history") as history,
        ):
            app = AppTest.from_file("app.py", default_timeout=30)
            app.query_params["strategy"] = "small"
            app.run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.tabs[-1].get("page_link")), 1)
        self.assertFalse(app.number_input)
        self.assertFalse(app.subheader)
        kospi.assert_not_called()
        snowball.assert_not_called()
        history.assert_not_called()

    def test_saving_ratio_updates_both_current_month_and_backtest(self):
        closes = pd.to_datetime(["2026-11-02", "2026-11-03"])
        result = pd.DataFrame({"포트 일간": [.10, 0], "포트 누적": [.10, .10]}, index=closes)
        holding = live.CurrentHoldings(pd.DataFrame([{"종목명": "예시"}]), result)
        zero = live.CurrentHoldings(holding.holdings, result * 0)
        history = pd.DataFrame(0., index=["2026-09", "2026-10"], columns=LEGS)
        history["kospi"] = [.10, -.01]
        snow = dict.fromkeys(SNOW, zero.performance["포트 누적"])
        with (
            patch.object(view, "current_month", return_value="2026-11"),
            patch.object(view, "load_history", return_value=history),
            patch.object(live, "kospi_current", return_value=holding),
            patch.object(live, "smallcap_current", return_value=zero),
            patch.object(live, "snowball_current", return_value=(snow, holding.holdings)),
        ):
            app = AppTest.from_file("app.py", default_timeout=30).run()
            before = {metric.label: metric.value for metric in app.metric}
            app.number_input[0].set_value(527.0)
            app.number_input[1].set_value(0.0)
            app.number_input[2].set_value(0.0)
            next(button for button in app.button if button.label == "비율 저장").click().run()
        self.assertEqual(len(app.exception), 0)
        after = {metric.label: metric.value for metric in app.metric}
        self.assertEqual(before["코스피200"], "44.0%")
        self.assertEqual(after["코스피200"], "100.0%")
        self.assertNotEqual(before["MDD"], after["MDD"])
        self.assertEqual(after["이번 달 누적"], "+10.00%")


if __name__ == "__main__":
    unittest.main()
