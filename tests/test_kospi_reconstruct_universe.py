"""과거 시총 후보군에서 거래량0을 별도 정책으로 다루는 회귀 검증."""
from pathlib import Path
import sys
import tempfile
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '기록' / '검토'))
from kospi_overlap_audit import reconstruct


class StrictUniverseTests(unittest.TestCase):
    def test_zero_volume_policy_preserves_original_default_and_missing_returns(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as folder:
            tmp_path = Path(folder)
            for year in range(2008, 2015):
                frame = pd.DataFrame({
                    'Date': pd.to_datetime([f'{year}-12-30', f'{year}-12-30']),
                    'Code': ['000010', '000020'], 'Name': ['거래량0', '거래종목'],
                    'Close': [100, 100], 'Changes': [0, 0], 'Volume': [0, 10],
                    'Marcap': [2000, 1000], 'MarketId': ['STK', 'STK'],
                })
                frame.to_parquet(tmp_path / f'marcap-{year}.parquet', index=False)
            original, _ = reconstruct(tmp_path, start_month='2014-01', end_month='2014-01')
            strict, _ = reconstruct(tmp_path, start_month='2014-01', end_month='2014-01',
                                    exclude_zero_volume=False)
            self.assertEqual(original['종목코드'].tolist(), ['000020'])
            self.assertEqual(strict['종목코드'].tolist(), ['000010', '000020'])
            self.assertEqual(strict['거래량'].tolist(), [0, 10])
            self.assertTrue(strict['종목선정일'].eq('2013-12-30').all())
            self.assertTrue(strict['이번달수익률'].isna().all())


if __name__ == '__main__':
    unittest.main()
