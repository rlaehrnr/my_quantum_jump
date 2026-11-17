import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from utils.static_allocation import (
    PLANS, allocate, default_rows, read_settings, write_settings,
)


PAGE = Path(__file__).resolve().parents[1] / "pages" / "8_정적자산배분.py"


class FakeWorksheet:
    values = []

    def get(self, *args, **kwargs):
        return self.values

    def update(self, values, *, range_name, raw):
        self.values = values


class StaticAllocationTest(unittest.TestCase):
    def test_excel_weights(self):
        self.assertEqual([sum(a.weight for a in rows) for rows in PLANS.values()], [100, 100, 100, 100])
        self.assertEqual([a.weight for a in PLANS["kr_summer"][:4]], [10, 2, 3, 5])

    def test_round_lots_and_separate_cash_from_missing_quotes(self):
        rows = default_rows("kr_summer")
        result = allocate(15_000_000, rows, {"069500": 78_070})
        first = result.lines[0]
        self.assertEqual(first.target, Decimal("1500000"))
        self.assertEqual(first.shares, 19)
        self.assertEqual(first.purchase, Decimal("1483330"))
        self.assertEqual(result.lot_remainder, Decimal("16670"))
        self.assertEqual(result.planned_cash, Decimal("4500000"))
        self.assertEqual(result.pending, Decimal("9000000"))
        self.assertEqual(result.purchase_total + result.cash_remaining, 15_000_000)

    def test_us_dollars_and_grvt_exact_allocation(self):
        for plan, ewy_price in (("us", 12), ("us_summer", 8.4)):
            result = allocate(120, default_rows(plan), {"EWY": ewy_price})
            self.assertEqual(result.lines[0].shares, 1)
            self.assertEqual(result.lines[0].purchase, Decimal(str(ewy_price)))
            grvt_order = next(order for order, row in zip(result.lines, default_rows(plan)) if row["asset"].label == "GRVT")
            self.assertIsNone(grvt_order.shares)
            self.assertEqual(grvt_order.purchase, Decimal("12"))
            self.assertEqual(result.purchase_total + result.cash_remaining, 120)
    def test_sheet_roundtrip_persists_override_without_touching_defaults(self):
        sheet = FakeWorksheet()
        rows = default_rows("us")
        rows[0].update(ticker="FLKR", manual_price=25.75)
        write_settings(sheet, 15_000_000, 1420.75, {"us": rows})
        assets, currency, fx, saved = read_settings(sheet, ("us", "us_summer"))
        self.assertEqual((assets, currency, fx), (15_000_000, "USD", 1420.75))
        self.assertEqual(saved["us"][0], rows[0])
        self.assertEqual(default_rows("us")[0]["ticker"], "EWY")
        self.assertEqual(sheet.values[2][4:7], ["FLKR", 10, 25.75])

    def test_legacy_google_sheet_keeps_capital_and_refreshes_workbook_defaults(self):
        sheet = FakeWorksheet()
        rows = default_rows("kr_summer")
        rows[-1]["weight"] = 40
        write_settings(sheet, 15_004_321, None, {"kr_summer": rows})
        sheet.values[0] = sheet.values[0][:4]
        assets, currency, fx, saved = read_settings(sheet, ("kr_winter", "kr_summer"))
        self.assertEqual((assets, currency, fx), (15_004_321, "원", None))
        self.assertEqual(saved["kr_summer"][-1]["weight"], 30)
    def test_invalid_weights_never_produce_purchase_quantities(self):
        rows = default_rows("us")
        rows[0]["weight"] = 15
        self.assertIsNone(allocate(100_000, rows, {"EWY": 1}))


class StaticAllocationPageTest(unittest.TestCase):
    def setUp(self):
        history = patch("utils.static_allocation_performance.market_history", return_value=pd.DataFrame())
        self.market_history = history.start()
        self.addCleanup(history.stop)
        proxies = patch(
            "utils.static_allocation_performance.market_proxy_prices",
            return_value=(pd.DataFrame(), pd.DataFrame()),
        )
        proxies.start()
        self.addCleanup(proxies.stop)

    def test_all_default_tables_show_without_scrolling_in_the_grid(self):
        with patch("utils.static_allocation_quotes.fetch_quotes", return_value={}):
            app = AppTest.from_file(str(PAGE)).run()
        self.assertFalse(app.exception)
        self.assertEqual({tab.label for tab in app.tabs}, {"한국", "미국", "11월–4월", "5월–10월"})
        self.assertNotIn("정적 배분 비율 (%)", [x.label for x in app.number_input])
        charts = [x for x in app.dataframe if "매수 (주)" in x.value]
        self.assertEqual([len(x.value) for x in charts], [12, 13, 16, 16])
        self.assertTrue(all(x.proto.row_height == 32 for x in charts))
        self.assertEqual(
            [widget.label for widget in app.number_input],
            ["환율 직접 입력", "총 자산 (만원)", "총 자산 (USD)", "총 자산 (원)"],
        )
        self.assertTrue(any("⇄" in item.value for item in app.markdown))
        self.assertEqual(app.number_input(key="static_kr_manwon_integer").proto.format, "%d")
        self.assertIn("칠레 주식", list(charts[-1].value["투자 대상"]))
        self.assertIn("브라질 주식", list(charts[-1].value["투자 대상"]))
        self.assertTrue(all("기준 시각 (KST)" in chart.value for chart in charts))

    def test_performance_is_rendered_in_the_default_market_tab(self):
        sessions = pd.to_datetime(["2026-04-30", "2026-05-04", "2026-05-29", "2026-06-01"])
        korean_tickers = {a.ticker for key in ("kr_winter", "kr_summer") for a in PLANS[key] if a.ticker}
        self.market_history.return_value = pd.DataFrame(
            {ticker: [100.0, 90.0, 120.0, 120.0] for ticker in korean_tickers}, index=sessions,
        )
        with (
            patch("utils.static_allocation_quotes.fetch_quotes", return_value={}),
            patch("utils.static_allocation_performance.market_dates",
                  return_value=(pd.Period("2026-06", freq="M"), sessions[-1].date())),
        ):
            app = AppTest.from_file(str(PAGE)).run()
        self.assertFalse(app.exception)
        self.assertEqual(next(m.value for m in app.metric if m.label == "이번 달 누적 수익률"), "+0.00%")
        self.assertEqual(next(m.value for m in app.metric if m.label == "누적 수익률"), "+14.00%")
        self.assertEqual(len(app.get("plotly_chart")), 2)
        drawdowns = next(item.value for item in app.dataframe if "MDD" in item.value)
        self.assertEqual(drawdowns.iloc[0]["MDD"], "-7.00%")
        self.assertEqual(drawdowns.iloc[0]["기간"], "2026-05-04 ~ 2026-05-04")
        app.toggle(key="static_midterm").set_value(True).run()
        self.assertFalse(app.exception)
        self.assertEqual(next(m.value for m in app.metric if m.label == "누적 수익률"), "+7.00%")
        self.assertTrue(any("현금 65%" in item.value for item in app.caption))
    def test_dollar_and_won_inputs_update_each_other(self):
        with patch("utils.static_allocation_quotes.fetch_quotes", return_value={}):
            app = AppTest.from_file(str(PAGE)).run()
            usd = "static_us_dollars"
            krw = "static_us_won"
            fx = "static_us_fx"
            app.number_input(key=fx).set_value(1_250.0)
            app.number_input(key=usd).set_value(120.0)
            app.run()
            self.assertEqual(app.number_input(key=krw).value, 150_000)

            app.number_input(key=krw).set_value(200_000).run()
            self.assertEqual(app.number_input(key=usd).value, 160.0)
            app.number_input(key=fx).set_value(1_000.0).run()
            self.assertEqual(app.number_input(key=krw).value, 200_000)
            self.assertEqual(app.number_input(key=usd).value, 200.0)

            app.number_input(key=usd).set_value(None).run()
            self.assertIsNone(app.number_input(key=krw).value)
            self.assertFalse(app.exception)
    def test_save_then_new_browser_loads_settings_and_recalculates_in_usd(self):
        from unittest.mock import Mock
        from utils.static_allocation_quotes import Quote

        worksheets = {"한국": FakeWorksheet(), "미국": FakeWorksheet()}
        connection = Mock()
        connection.open_by_key.return_value.worksheet.side_effect = worksheets.__getitem__
        quotes = {"EWY": Quote(12.0, None, "Yahoo 1분봉")}
        with (
            patch("gspread.authorize", return_value=connection),
            patch("google.oauth2.service_account.Credentials.from_service_account_info"),
            patch("utils.static_allocation_quotes.fetch_quotes", return_value=quotes),
        ):
            app = AppTest.from_file(str(PAGE))
            app.secrets["static_allocation_spreadsheet_id"] = "test"
            app.secrets["google_credentials"] = "{}"
            app.run()
            app.number_input(key="static_us_dollars").set_value(120.0)
            app.number_input(key="static_us_fx").set_value(1_250.0)
            app.button(key="static_refresh_quotes").click()
            app.button(key="static_save_us").click()
            app.run()
            self.assertFalse(app.exception)
            self.assertTrue(app.success)

            new_browser = AppTest.from_file(str(PAGE))
            new_browser.secrets.update(app.secrets)
            new_browser.run()
            self.assertFalse(new_browser.exception)
            self.assertEqual(new_browser.number_input(key="static_us_dollars").value, 120.0)
            self.assertEqual(new_browser.number_input(key="static_us_fx").value, 1_250.0)
            self.assertEqual(new_browser.number_input(key="static_us_won").value, 150_000)
            result = next(x.value for x in new_browser.dataframe if "매수·배정 금액 (USD)" in x.value)
            self.assertEqual(result.iloc[0]["매수 (주)"], 1)
            self.assertEqual(result.iloc[0]["매수·배정 금액 (USD)"], 12)

            new_browser.number_input(key="static_us_won").set_value(150_001)
            new_browser.button(key="static_save_us").click()
            new_browser.run()
            self.assertFalse(new_browser.exception)
            self.assertEqual(worksheets["미국"].values[0][:2], ["총 자산 (원)", 150_001])

            won_browser = AppTest.from_file(str(PAGE))
            won_browser.secrets.update(app.secrets)
            won_browser.run()
            self.assertFalse(won_browser.exception)
            self.assertEqual(won_browser.number_input(key="static_us_won").value, 150_001)
            self.assertEqual(won_browser.number_input(key="static_us_dollars").value, 120.0)
