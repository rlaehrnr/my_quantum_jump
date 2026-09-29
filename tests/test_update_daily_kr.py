import unittest
from datetime import datetime
from unittest.mock import patch

import pandas as pd

import update_daily_kr


class FixedDateTime(datetime):
    @classmethod
    def today(cls):
        return cls(2026, 9, 29, 9, 41)


class LastBusinessDayTests(unittest.TestCase):
    def test_ignores_intraday_krx_cache_even_when_ks11_is_stale(self):
        stale_index = pd.DataFrame(
            {"Volume": [1_000_001]},
            index=pd.to_datetime(["2026-09-17"]),
        )

        def read_cache(url, *args, **kwargs):
            if url.endswith(("/2026-09-29.csv", "/2026-09-28.csv")):
                return pd.DataFrame({"Code": ["005930"], "MarketId": ["STK"]})
            raise AssertionError(f"예상하지 않은 캐시 조회: {url}")

        with (
            patch.object(update_daily_kr, "datetime", FixedDateTime),
            patch.object(update_daily_kr.fdr, "DataReader", return_value=stale_index),
            patch.object(update_daily_kr.pd, "read_csv", side_effect=read_cache),
        ):
            actual = update_daily_kr.get_last_business_day_kr()

        self.assertEqual("2026-09-28", actual)


class ProcessTickerTests(unittest.TestCase):
    def test_ignores_price_rows_after_the_reported_base_date(self):
        history = pd.DataFrame(
            {
                "Close": [100.0, 200.0],
                "Volume": [1_000, 2_000],
            },
            index=pd.to_datetime(["2026-09-28", "2026-09-29"]),
        )
        row = pd.Series(
            {
                "Code": "005930",
                "Name": "삼성전자",
                "시장": "KOSPI",
                "Marcap": 1_000_000,
            }
        )
        dates = {
            "1개월": pd.Timestamp("2026-08-31"),
            "3개월": pd.Timestamp("2026-06-30"),
            "6개월": pd.Timestamp("2026-03-31"),
            "12개월": pd.Timestamp("2025-09-30"),
        }

        with patch.object(update_daily_kr.fdr, "DataReader", return_value=history):
            _, record, trimmed_history = update_daily_kr.process_ticker_kr(
                row,
                pd.Timestamp("2025-09-15"),
                datetime(2026, 9, 29, 9, 41),
                dates,
                "2026-09-28",
            )

        self.assertEqual(100.0, record["종가"])
        self.assertEqual(pd.Timestamp("2026-09-28"), trimmed_history.index[-1])


if __name__ == "__main__":
    unittest.main()
