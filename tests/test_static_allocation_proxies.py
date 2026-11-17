import unittest

import pandas as pd

from utils.static_allocation_proxies import extend_korean_prices, prior_foreign_close


class StaticProxyTest(unittest.TestCase):
    def test_foreign_prices_only_use_dates_before_the_korean_session(self):
        source = pd.Series([100.0, 110.0, 999.0], index=pd.to_datetime([
            "2026-04-27", "2026-04-28", "2026-04-29",
        ]))
        sessions = pd.to_datetime(["2026-04-28", "2026-04-29", "2026-05-20"])
        result = prior_foreign_close(source, sessions)
        self.assertEqual(list(result.iloc[:2]), [100.0, 110.0])
        self.assertTrue(pd.isna(result.iloc[-1]))

    def test_splice_preserves_proxy_growth_without_resetting_actual_prices(self):
        sessions = pd.to_datetime(["2026-04-27", "2026-04-28", "2026-04-29", "2026-04-30"])
        actual = pd.DataFrame({"0189B0": [None, None, 50.0, 51.0]}, index=sessions)
        source_dates = pd.to_datetime(["2026-04-26", "2026-04-27", "2026-04-28", "2026-04-29"])
        foreign = pd.DataFrame({
            "SLV": [100.0, 120.0, 125.0, 999.0],
            "KRW=X": [1000.0, 1000.0, 1200.0, 1000.0],
        }, index=source_dates)
        result = extend_korean_prices(actual, sessions, foreign, pd.DataFrame(), {"0189B0"})
        self.assertAlmostEqual(result.loc[sessions[0], "0189B0"], 50 * 100 / 150)
        self.assertAlmostEqual(result.loc[sessions[1], "0189B0"], 40.0)
        self.assertEqual(list(result.loc[sessions[2]:, "0189B0"]), [50.0, 51.0])

    def test_no_filling_after_the_actual_etf_begins(self):
        sessions = pd.to_datetime(["2026-04-27", "2026-04-28", "2026-04-29"])
        actual = pd.DataFrame({"385560": [None, 10.0, None]}, index=sessions)
        domestic = pd.DataFrame({"148070": [95.0, 100.0, 105.0]}, index=sessions)
        result = extend_korean_prices(actual, sessions, pd.DataFrame(), domestic, {"385560"})
        self.assertEqual(result["385560"].iloc[0], 9.5)
        self.assertTrue(pd.isna(result["385560"].iloc[-1]))
