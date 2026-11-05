import unittest
import tempfile
from pathlib import Path

import pandas as pd

from utils.kospi_history import build_monthly_archive, write_monthly_archives, with_return_prices


def _row(day, code, close, marcap, *, name="테스트", volume=100, market_id="STK"):
    return {
        "Date": day,
        "Code": code,
        "Name": name,
        "Close": close,
        "Volume": volume,
        "Marcap": marcap,
        "MarketId": market_id,
        "Market": "KOSPI",
    }


class KOSPIHistoryArchiveTests(unittest.TestCase):
    def test_corporate_action_uses_reference_price_not_raw_close_ratio(self):
        source = pd.DataFrame([
            dict(_row('2009-11-30', '000010', 100, 1000), Changes=0),
            dict(_row('2009-12-31', '000010', 110, 1100), Changes=10),
            dict(_row('2010-01-29', '000010', 550, 5500), Changes=0),
        ])
        result = build_monthly_archive(with_return_prices(source), '2010-01', '2010-01', top_n=1)
        self.assertEqual(10.0, result.loc[0, '1개월(%)'])
        self.assertEqual(0.0, result.loc[0, '이번달수익률'])
        self.assertEqual(110.0, result.loc[0, '종가'])

    def test_uses_month_end_top_common_stocks_and_computes_returns(self):
        source = pd.DataFrame(
            [
                _row("2009-11-30", "000010", 100, 1_000, name="가"),
                _row("2009-11-30", "000020", 100, 900, name="나"),
                _row("2009-11-30", "000011", 100, 2_000, name="우선주"),
                _row("2009-12-31", "000010", 120, 1_100, name="가"),
                _row("2009-12-31", "000020", 90, 1_200, name="나"),
                _row("2009-12-31", "000011", 110, 3_000, name="우선주"),
                _row("2010-01-29", "000010", 132, 1_300, name="가"),
                _row("2010-01-29", "000020", 81, 1_100, name="나"),
                _row("2010-01-29", "000011", 121, 3_100, name="우선주"),
            ]
        )

        actual = build_monthly_archive(source, "2010-01", "2010-01", top_n=2)

        self.assertEqual(["000020", "000010"], actual["종목코드"].tolist())
        self.assertEqual([1, 2], actual["순위"].tolist())
        self.assertTrue((actual["투자월"] == "2010-01").all())
        self.assertTrue((actual["종목선정일"] == "2009-12-31").all())
        self.assertEqual(20.0, actual.loc[actual["종목코드"] == "000010", "1개월(%)"].iloc[0])
        self.assertEqual(10.0, actual.loc[actual["종목코드"] == "000010", "이번달수익률"].iloc[0])

    def test_keeps_missing_history_as_nan_instead_of_fabricating_a_return(self):
        source = pd.DataFrame(
            [
                _row("2009-12-31", "000010", 120, 1_100),
                _row("2010-01-29", "000010", 132, 1_300),
            ]
        )

        actual = build_monthly_archive(source, "2010-01", "2010-01", top_n=1)

        self.assertTrue(pd.isna(actual.loc[0, "1개월(%)"]))
        self.assertEqual(10.0, actual.loc[0, "이번달수익률"])

    def test_excludes_a_zero_volume_stock_from_the_month_end_universe(self):
        source = pd.DataFrame(
            [
                _row("2009-12-31", "000010", 100, 1_000, volume=100),
                _row("2009-12-31", "000020", 100, 900, volume=100),
                _row("2009-12-31", "000030", 100, 9_000, volume=0),
                _row("2010-01-29", "000010", 110, 1_100, volume=100),
                _row("2010-01-29", "000020", 110, 1_000, volume=100),
                _row("2010-01-29", "000030", 110, 9_900, volume=0),
            ]
        )

        actual = build_monthly_archive(source, "2010-01", "2010-01", top_n=2)

        self.assertEqual(["000010", "000020"], actual["종목코드"].tolist())

    def test_writes_one_utf8_sig_file_per_investment_month(self):
        source = pd.DataFrame(
            [
                _row("2009-12-31", "000010", 100, 1_000),
                _row("2010-01-29", "000010", 120, 1_100),
                _row("2010-02-26", "000010", 132, 1_300),
            ]
        )

        with tempfile.TemporaryDirectory() as directory:
            written = write_monthly_archives(source, "2010-01", "2010-01", directory, top_n=1)
            path = Path(directory) / "only_kospi_2010_01.csv"
            self.assertEqual([path], written)
            restored = pd.read_csv(path, encoding="utf-8-sig", dtype={"종목코드": str})

        self.assertEqual("000010", restored.loc[0, "종목코드"])
        self.assertEqual("2010-01", restored.loc[0, "투자월"])


if __name__ == "__main__":
    unittest.main()
