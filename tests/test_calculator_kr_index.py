import unittest
from unittest.mock import patch

import pandas as pd

from utils import calculator


def _index_history(end_date, close):
    index = pd.bdate_range(end=end_date, periods=240)
    return pd.DataFrame(
        {
            "Open": close,
            "High": close,
            "Low": close,
            "Close": close,
            "Volume": 100_000,
            "Change": 0.0,
        },
        index=index,
    )


class KoreaIndexSourceTests(unittest.TestCase):
    def test_kospi_current_price_uses_the_complete_naver_history(self):
        def read_index(symbol, start, end):
            if symbol == "KS11":
                return _index_history("2026-09-17", 6724.34)
            if symbol == "NAVER:KOSPI":
                return _index_history("2026-09-28", 6889.74)
            raise AssertionError(f"예상하지 않은 지수: {symbol}")

        with patch("FinanceDataReader.DataReader", side_effect=read_index):
            current, _ = calculator.get_kospi_ma_all.__wrapped__("2026-09-28")

        self.assertEqual(6889.74, current)

    def test_kosdaq_current_price_uses_the_complete_naver_history(self):
        def read_index(symbol, start, end):
            if symbol == "KQ11":
                return _index_history("2026-09-17", 821.67)
            if symbol == "NAVER:KOSDAQ":
                return _index_history("2026-09-28", 846.58)
            raise AssertionError(f"예상하지 않은 지수: {symbol}")

        with patch("FinanceDataReader.DataReader", side_effect=read_index):
            current, _ = calculator.get_kosdaq_ma_all.__wrapped__("2026-09-28")

        self.assertEqual(846.58, current)


if __name__ == "__main__":
    unittest.main()
