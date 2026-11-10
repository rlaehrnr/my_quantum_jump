import unittest

import pandas as pd

from utils.calculator import select_kospi200_targets


class EntryPolicyTests(unittest.TestCase):
    def setUp(self):
        self.data = pd.DataFrame({
            '종목코드': ['000010', '000020', '000030', '000040'],
            '1개월(%)': [40, 30, 20, 10], '3개월(%)': [40, 30, 20, 10],
            '6개월(%)': [40, 30, 20, 10], '12개월(%)': [40, 30, 20, 10],
            '거래량': [0, 100, 100, 100],
        })

    def test_cash_keeps_original_slot_and_next_fills_with_lower_rank(self):
        arguments = ((1, 2), (1, 1), 100, 100)
        legacy, _ = select_kospi200_targets(self.data, *arguments)
        cash, _ = select_kospi200_targets(self.data, *arguments, entry_policy='cash')
        next_rank, _ = select_kospi200_targets(self.data, *arguments, entry_policy='next')
        self.assertEqual(legacy['종목코드'].tolist(), ['000010', '000020'])
        self.assertNotIn('_cash', legacy.columns)
        self.assertEqual(cash['종목코드'].tolist(), ['000010', '000020'])
        self.assertEqual(cash['_cash'].tolist(), [True, False])
        self.assertEqual(next_rank['종목코드'].tolist(), ['000020', '000030'])
        self.assertEqual(next_rank['_cash'].tolist(), [False, False])

    def test_insufficient_replacements_preserve_cash_slot(self):
        self.data.loc[2:, '거래량'] = 0
        selected, _ = select_kospi200_targets(self.data, (1, 3), (1, 1), 100, 100,
                                             entry_policy='next')
        self.assertEqual(len(selected), 3)
        self.assertEqual(int(selected['_cash'].sum()), 2)
        self.assertEqual(selected['종목코드'].nunique(), 3)

        self.data.loc[0, '거래량'] = float('nan')
        selected, _ = select_kospi200_targets(self.data, (1, 3), (1, 1), 100, 100,
                                             entry_policy='next')
        self.assertEqual(len(selected), 3)
        self.assertEqual(int(selected['_cash'].sum()), 2)

    def test_replacement_stays_in_momentum_qualifiers(self):
        _, selected = select_kospi200_targets(self.data, (1, 2), (1, 1), 100, 100,
                                              entry_policy='next')
        # 달리는 말 1M 상위10% 조건을 통과한 유일한 종목이 거래 불가다.
        self.assertEqual(selected['종목코드'].tolist(), ['000010'])
        self.assertTrue(selected['_cash'].all())


if __name__ == '__main__':
    unittest.main()
