import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

import update_snowball


class DividendObservationSelectionTests(unittest.TestCase):
    def test_uses_fridays_quote_instead_of_the_following_saturday_estimate(self):
        raw = pd.Series(
            [1.06, 1.07, 1.05],
            index=pd.to_datetime(["2026-09-30", "2026-10-30", "2026-10-31"]),
        )

        actual = update_snowball.select_dividend_monthly_observations(
            raw, pd.Timestamp("2026-10-31")
        )

        self.assertEqual(
            {pd.Period("2026-09", "M"): 1.06, pd.Period("2026-10", "M"): 1.07},
            actual.to_dict(),
        )

    def test_excludes_future_month_estimates_before_their_observation_date(self):
        raw = pd.Series(
            [1.06, 1.05],
            index=pd.to_datetime(["2026-09-30", "2026-10-31"]),
        )

        actual = update_snowball.select_dividend_monthly_observations(
            raw, pd.Timestamp("2026-10-03")
        )

        self.assertEqual({pd.Period("2026-09", "M"): 1.06}, actual.to_dict())

    def test_keeps_a_weekend_month_end_when_no_trade_day_quote_exists(self):
        raw = pd.Series([1.16], index=pd.to_datetime(["2026-02-28"]))

        actual = update_snowball.select_dividend_monthly_observations(
            raw, pd.Timestamp("2026-03-01")
        )

        self.assertEqual({pd.Period("2026-02", "M"): 1.16}, actual.to_dict())

    def test_update_writes_the_selected_current_month_value(self):
        selected = pd.Series({pd.Period("2026-10", "M"): 1.07})
        with tempfile.TemporaryDirectory(dir=".") as directory:
            with (
                patch.object(update_snowball, "MONTHLY_DIR", directory),
                patch.object(update_snowball, "fetch_div_multpl", return_value=selected),
                patch("builtins.print"),
            ):
                self.assertTrue(update_snowball.update_dividend())

            written = pd.read_csv(f"{directory}/SP500_DIV.csv", encoding="utf-8-sig")
        self.assertEqual("2026-10-31", written.loc[0, "날짜"])
        self.assertEqual(1.07, written.loc[0, "종가"])


if __name__ == "__main__":
    unittest.main()
