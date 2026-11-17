import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

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
        self.assertEqual([sum(a.weight for a in rows) for rows in PLANS.values()], [100, 100, 100])
        self.assertEqual([a.weight for a in PLANS["kr_summer"][:4]], [10, 2, 3, 5])

    def test_round_lots_and_separate_cash_from_missing_quotes(self):
        rows = default_rows("kr_summer")
        result = allocate(15_000_000, rows, {"069500": 78_070})
        first = result.lines[0]
        self.assertEqual(first.target, Decimal("1500000"))
        self.assertEqual(first.shares, 19)
        self.assertEqual(first.purchase, Decimal("1483330"))
        self.assertEqual(result.lot_remainder, Decimal("16670"))
        self.assertEqual(result.planned_cash, Decimal("6000000"))
        self.assertEqual(result.pending, Decimal("7500000"))
        self.assertEqual(result.purchase_total + result.cash_remaining, 15_000_000)

    def test_us_fx_exact_boundary_and_external_reserve(self):
        result = allocate(150_000, default_rows("us"), {"EWY": 12}, fx=1_250)
        self.assertEqual(result.lines[0].shares, 1)
        self.assertEqual(result.lines[0].purchase, 15_000)
        self.assertEqual(result.external, 15_000)
        self.assertIsNone(allocate(150_000, default_rows("us"), {"EWY": 12}, fx=None).lines[0].shares)
        self.assertEqual(allocate(149_999, default_rows("us"), {"EWY": 12}, fx=1_250).lines[0].shares, 0)

    def test_sheet_roundtrip_persists_override_without_touching_defaults(self):
        sheet = FakeWorksheet()
        rows = default_rows("us")
        rows[0].update(ticker="FLKR", manual_price=25.75)
        write_settings(sheet, 15_000_000, 1420.75, {"us": rows})
        assets, fx, saved = read_settings(sheet, ("us",))
        self.assertEqual((assets, fx), (15_000_000, 1420.75))
        self.assertEqual(saved["us"][0], rows[0])
        self.assertEqual(default_rows("us")[0]["ticker"], "EWY")
        self.assertEqual(sheet.values[2][4:7], ["FLKR", 10, 25.75])

    def test_invalid_weights_never_produce_purchase_quantities(self):
        rows = default_rows("us")
        rows[0]["weight"] = 15
        self.assertIsNone(allocate(100_000, rows, {"EWY": 1}, fx=1250))


class StaticAllocationPageTest(unittest.TestCase):
    def test_all_default_tables_show_without_scrolling_in_the_grid(self):
        with patch("utils.static_allocation_quotes.fetch_quotes", return_value={}):
            app = AppTest.from_file(str(PAGE)).run()
        self.assertFalse(app.exception)
        self.assertEqual({tab.label for tab in app.tabs}, {"한국", "미국", "11월–4월", "5월–10월"})
        self.assertNotIn("정적 배분 비율 (%)", [x.label for x in app.number_input])
        charts = [x for x in app.dataframe if "목표 금액 (원)" in x.value]
        self.assertEqual([len(x.value) for x in charts], [12, 13, 16])
        self.assertTrue(all(x.proto.row_height == 32 for x in charts))

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
            app.number_input(key="static_us_assets").set_value(150_000)
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
            self.assertEqual(new_browser.number_input(key="static_us_assets").value, 150_000)
            self.assertEqual(new_browser.number_input(key="static_us_fx").value, 1_250.0)
            result = next(x.value for x in new_browser.dataframe if "매수 금액 (USD)" in x.value)
            self.assertEqual(result.iloc[0]["매수 (주)"], 1)
            self.assertEqual(result.iloc[0]["매수 금액 (USD)"], 12)
